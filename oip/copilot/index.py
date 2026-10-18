"""Embeddings, vector store and keyword index for the copilot.

Embedder: LSA by default (TF-IDF unigrams+bigrams -> truncated SVD -> unit vectors),
which needs no model download. If sentence-transformers is installed and
OIP_EMBEDDER=st, all-MiniLM-L6-v2 is used instead. Either way vectors are
stored with their chunk metadata in data/vectorstore/.

Keyword index: Okapi BM25 over the same chunks. Retrieval fuses both rankings
(see answer.py), because dense vectors miss exact terms such as queue codes and
document IDs, while BM25 misses paraphrases.
"""
from __future__ import annotations

import json
import math
import os
import pickle
import re
import time
from collections import Counter

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from oip import config
from oip.copilot.documents import Chunk, chunk_documents, expand_abbreviations, load_documents

STOP = set("""a an and are as at be by for from has have how i in is it its of on or that the this to was were what when which
who why will with do does did can should we our you your if not no than then there these those into about after before
during over under per each any all more most""".split())
DEFAULT_CHUNK_WORDS = 160


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[str], k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.tokens = [tokenize(d) for d in docs]
        self.len = np.array([len(t) for t in self.tokens], float)
        self.avg = float(self.len.mean()) if len(self.len) else 0
        df = Counter(t for toks in self.tokens for t in set(toks))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(t) for t in self.tokens]

    def scores(self, query: str) -> np.ndarray:
        q = tokenize(query)
        out = np.zeros(len(self.tf))
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            out[i] = s
        return out


class LSAEmbedder:
    name = "lsa-tfidf-svd"

    def __init__(self, dims=128):
        self.dims = dims
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english", min_df=1)
        self.svd = None

    def fit(self, texts):
        X = self.vec.fit_transform([expand_abbreviations(t) for t in texts])
        k = max(2, min(self.dims, X.shape[0] - 1, X.shape[1] - 1))
        self.svd = TruncatedSVD(n_components=k, random_state=7).fit(X)
        return self

    def encode(self, texts):
        X = self.vec.transform([expand_abbreviations(t) for t in texts])
        return normalize(self.svd.transform(X))


class STEmbedder:
    name = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self):
        from sentence_transformers import SentenceTransformer  # optional dependency
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def fit(self, texts):
        return self

    def encode(self, texts):
        return np.asarray(self.model.encode(list(texts), normalize_embeddings=True))


def make_embedder():
    if os.environ.get("OIP_EMBEDDER") == "st":
        try:
            return STEmbedder()
        except Exception:
            pass
    return LSAEmbedder()


class KBIndex:
    def __init__(self, chunks: list[Chunk], embedder, vectors: np.ndarray, chunk_words: int):
        self.chunks = chunks
        self.embedder = embedder
        self.vectors = vectors
        self.chunk_words = chunk_words
        self.bm25 = BM25([expand_abbreviations(c.text) for c in chunks])

    @classmethod
    def build(cls, chunk_words=DEFAULT_CHUNK_WORDS):
        docs = load_documents()
        chunks = chunk_documents(docs, chunk_words=chunk_words)
        emb = make_embedder().fit([c.text for c in chunks])
        vecs = emb.encode([c.text for c in chunks]).astype(np.float32)
        return cls(chunks, emb, vecs, chunk_words)

    def save(self, path=None):
        path = path or config.VECTOR_DIR
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        (path / "chunks.json").write_text(json.dumps([c.to_dict() for c in self.chunks]))
        if isinstance(self.embedder, LSAEmbedder):
            with open(path / "embedder.pkl", "wb") as f:
                pickle.dump(self.embedder, f)
        (path / "meta.json").write_text(json.dumps({"embedder": self.embedder.name, "chunk_words": self.chunk_words,
                                                    "chunks": len(self.chunks), "dims": int(self.vectors.shape[1]),
                                                    "built_at": time.strftime("%Y-%m-%d %H:%M:%S")}))

    @classmethod
    def load(cls, path=None):
        path = path or config.VECTOR_DIR
        meta = json.loads((path / "meta.json").read_text())
        chunks = [Chunk(**c) for c in json.loads((path / "chunks.json").read_text())]
        vecs = np.load(path / "vectors.npy")
        if meta["embedder"].startswith("lsa"):
            with open(path / "embedder.pkl", "rb") as f:
                emb = pickle.load(f)
        else:
            emb = STEmbedder()
        return cls(chunks, emb, vecs, meta["chunk_words"])


_INDEX: KBIndex | None = None


def get_index() -> KBIndex:
    global _INDEX
    if _INDEX is None:
        if (config.VECTOR_DIR / "meta.json").exists():
            _INDEX = KBIndex.load()
        else:
            _INDEX = KBIndex.build()
            _INDEX.save()
    return _INDEX


def build_index(chunk_words: int | None = None, verbose=True) -> KBIndex:
    global _INDEX
    from oip.copilot.evaluate import choose_chunk_size
    if chunk_words is None:
        chunk_words = choose_chunk_size()
    idx = KBIndex.build(chunk_words)
    idx.save()
    _INDEX = idx
    if verbose:
        print(f"  [copilot] {len(idx.chunks)} chunks from {len({c.doc_id for c in idx.chunks})} documents; "
              f"{idx.embedder.name}, {idx.vectors.shape[1]} dims, chunk size {chunk_words} words", flush=True)
    return idx
