"""Knowledge base loading and chunking.

Documents are Markdown with a small front-matter block (doc_id, title, doc_type,
owner, version, effective). The metric handbook (MET-01) is generated from the
metric registry so the copilot can never disagree with the dashboards.

Chunking: split by heading into sections, then pack paragraphs into chunks of
about `chunk_words` words with ~20% overlap. Every chunk starts with a
contextual header ("Title > Section") so a passage still makes sense on its own.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from oip import config

ABBREVIATIONS = {
    "aht": "average handle time", "acw": "after call work", "sla": "service level agreement", "sl": "service level",
    "fcr": "first contact resolution", "csat": "customer satisfaction", "rta": "real time analyst adherence",
    "wfm": "workforce management", "kyc": "know your customer", "pii": "personal data", "qa": "quality audit",
    "rca": "root cause analysis", "asa": "average speed of answer", "tl": "team leader", "wape": "forecast error",
}


@dataclass
class Doc:
    doc_id: str
    title: str
    doc_type: str
    owner: str
    version: str
    effective: str
    body: str


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    doc_type: str
    section: str
    text: str
    words: int

    def to_dict(self):
        return asdict(self)


def _front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def metric_handbook() -> Doc:
    from oip.warehouse.metrics import METRICS
    lines = ["# Purpose", "Official definitions of every metric shown on the Operations Intelligence Platform. "
             "Generated from the metric registry, so the dashboards, Power BI measures and this handbook always agree."]
    for m in METRICS:
        lines.append(f"# {m.label}")
        lines.append(f"{m.definition} Business question: {m.business_question or 'n/a'}")
        lines.append(f"Numerator: {m.numerator}. Denominator: {m.denominator}. Exclusions: {m.exclusions}. "
                     f"Better when: {'higher' if m.direction == 'up' else 'lower' if m.direction == 'down' else 'within the target band'}.")
    return Doc("MET-01", "Metric Definitions Handbook", "Reference", "Reporting and Analytics", "generated", "2026-06-16", "\n\n".join(lines))


def load_documents() -> list[Doc]:
    docs = []
    for p in sorted(config.KB_DIR.glob("*.md")):
        meta, body = _front_matter(p.read_text())
        docs.append(Doc(meta.get("doc_id", p.stem), meta.get("title", p.stem), meta.get("doc_type", "Document"),
                        meta.get("owner", ""), meta.get("version", ""), meta.get("effective", ""), body.strip()))
    docs.append(metric_handbook())
    return docs


def _tables_to_sentences(text: str) -> str:
    """Markdown tables become one sentence per row ('Condition: x; Escalate to: y; Within: z.') so rows survive chunking."""
    out, header = [], None
    for line in text.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if header is None:
                header = cells
                continue
            out.append("; ".join(f"{h}: {c}" for h, c in zip(header, cells)) + ".")
        else:
            header = None
            out.append(line)
    return "\n".join(out)


def _sections(body: str) -> list[tuple[str, str]]:
    parts = re.split(r"^#\s+(.+)$", body, flags=re.M)
    out = []
    if parts[0].strip():
        out.append(("Overview", parts[0].strip()))
    for i in range(1, len(parts), 2):
        out.append((parts[i].strip(), _tables_to_sentences(parts[i + 1].strip())))
    return out


def chunk_documents(docs: list[Doc], chunk_words: int = 160, overlap: float = 0.2) -> list[Chunk]:
    chunks = []
    for d in docs:
        for sec, text in _sections(d.body):
            paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[-|\d]+[.)]? )", text) if p.strip()]
            words: list[str] = []
            buf: list[str] = []
            k = 0

            def flush():
                nonlocal buf, k
                if not buf:
                    return
                k += 1
                body_txt = " ".join(buf).strip()
                header = f"{d.title} > {sec}. "
                chunks.append(Chunk(f"{d.doc_id}#{len(chunks)}", d.doc_id, d.title, d.doc_type, sec, header + body_txt,
                                    len(body_txt.split())))
            for p in paras:
                pw = p.split()
                if buf and len(" ".join(buf).split()) + len(pw) > chunk_words:
                    flush()
                    tail = " ".join(buf).split()[-int(chunk_words * overlap):] if overlap else []
                    buf = [" ".join(tail)] if tail else []
                buf.append(p)
            flush()
    return chunks


def expand_abbreviations(text: str) -> str:
    extra = [ABBREVIATIONS[t] for t in re.findall(r"[a-z]+", text.lower()) if t in ABBREVIATIONS]
    return text + (" " + " ".join(extra) if extra else "")
