"""Retrieval-augmented answers with citations.

retrieve(): dense (embeddings) and BM25 rankings fused with Reciprocal Rank
Fusion, then Maximal Marginal Relevance to avoid near-duplicate passages.

answer(): builds a prompt from the numbered passages (plus optional live KPI
context) and asks the configured LLM to answer only from them, citing [n].
Providers: Anthropic API, a local Ollama model, or an extractive fallback that
needs no model at all (it quotes the most relevant sentences with citations).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

import numpy as np

from oip import config
from oip.copilot.documents import expand_abbreviations
from oip.copilot.index import KBIndex, get_index, tokenize

SYSTEM = (
    "You are the operations copilot for a contact-centre delivery team (voice, chat, email and back office). "
    "Answer using only the numbered sources and the live data block if present. Cite sources inline as [1], [2]; cite live data as [L]. "
    "Start with a direct one or two sentence answer, then give numbered recommended actions with an owner (RTA, team leader, WFM planner, "
    "operations manager, quality, client services) where actions are relevant. Never invent numbers, dates or policies. "
    "If the sources do not cover the question, say what is missing. Keep it under 220 words. Plain text, no markdown headings."
)


def retrieve(query: str, k: int = 5, doc_types: list[str] | None = None, index: KBIndex | None = None,
             mode: str = "hybrid", mmr_lambda: float = 0.7, pool: int = 20) -> list[dict]:
    idx = index or get_index()
    q = expand_abbreviations(query)
    dense = idx.vectors @ idx.embedder.encode([q])[0]
    sparse = idx.bm25.scores(q)
    mask = np.ones(len(idx.chunks), bool)
    if doc_types:
        mask = np.array([c.doc_type in doc_types for c in idx.chunks])
    ids = np.flatnonzero(mask)
    if mode == "dense":
        fused = {int(i): float(dense[i]) for i in ids}
    elif mode == "bm25":
        fused = {int(i): float(sparse[i]) for i in ids}
    else:
        rd = {int(i): r for r, i in enumerate(ids[np.argsort(-dense[ids])])}
        rs = {int(i): r for r, i in enumerate(ids[np.argsort(-sparse[ids])])}
        fused = {int(i): 1 / (60 + rd[int(i)]) + 1 / (60 + rs[int(i)]) for i in ids}
    if re.search(r"defin|measur|calculat|formula|denominator|numerator|what is the .* rate", query, re.I):
        for i in fused:
            if idx.chunks[i].doc_id == "MET-01":
                fused[i] += 0.01 if mode == "hybrid" else 0
    cand = sorted(fused, key=lambda i: -fused[i])[:pool]
    chosen: list[int] = []
    if mmr_lambda < 1 and len(cand) > k:
        rel = np.array([fused[i] for i in cand])
        rel = (rel - rel.min()) / (rel.max() - rel.min() + 1e-9)
        while len(chosen) < k:
            best, best_s = None, -1e9
            for j, i in enumerate(cand):
                if i in chosen:
                    continue
                div = max((float(idx.vectors[i] @ idx.vectors[c]) for c in chosen), default=0.0)
                s = mmr_lambda * rel[j] - (1 - mmr_lambda) * div
                if s > best_s:
                    best, best_s = i, s
            chosen.append(best)
    else:
        chosen = cand[:k]
    out = []
    for rank, i in enumerate(chosen):
        c = idx.chunks[i]
        out.append({"rank": rank + 1, "chunk_id": c.chunk_id, "doc_id": c.doc_id, "title": c.title, "doc_type": c.doc_type,
                    "section": c.section, "text": c.text, "score": round(float(fused[i]), 5),
                    "dense": round(float(dense[i]), 4), "bm25": round(float(sparse[i]), 3)})
    return out


def _prompt(question: str, passages: list[dict], live: str | None) -> str:
    src = "\n\n".join(f"[{p['rank']}] {p['doc_id']} · {p['title']} > {p['section']}\n{p['text']}" for p in passages)
    live_block = f"\n\nLIVE DATA [L] (from the platform, current filters):\n{live}" if live else ""
    return f"SOURCES:\n{src}{live_block}\n\nQUESTION: {question}"


def _anthropic(prompt: str, s: config.LLMSettings, timeout=60) -> str:
    body = json.dumps({"model": s.anthropic_model, "max_tokens": 900, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{s.anthropic_base.rstrip('/')}/v1/messages", data=body, method="POST",
                                 headers={"content-type": "application/json", "x-api-key": s.anthropic_key or "",
                                          "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _ollama(prompt: str, s: config.LLMSettings, timeout=120) -> str:
    body = json.dumps({"model": s.ollama_model, "stream": False, "options": {"temperature": 0.2},
                       "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{s.ollama_base.rstrip('/')}/api/chat", data=body, method="POST",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["message"]["content"].strip()


def _ollama_up(s: config.LLMSettings) -> bool:
    try:
        with urllib.request.urlopen(f"{s.ollama_base.rstrip('/')}/api/tags", timeout=0.6) as r:
            return r.status == 200
    except Exception:
        return False


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"^.*?>\s.*?\.\s", "", text, count=1)      # drop the contextual header
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])|\s(?=\d\.\s)|\s(?=-\s)|\s\|\s", text)
    return [p.strip(" -|") for p in parts if len(p.split()) >= 5]


ACTION_SECTIONS = ("recommendation", "actions", "prevention", "trigger", "overflow", "escalation", "treatment", "when callback",
                   "three weeks", "one week", "during the sale", "roster change", "coaching", "hold", "known issues", "detection")
IMPERATIVES = ["Move", "Add", "Keep", "Activate", "Re-apply", "Raise", "Pull", "Delay", "Offer", "Use", "Get", "Roster", "Approve", "Publish",
               "Watch", "Build", "Compare", "Ask", "Return", "Transfer", "Acknowledge", "Answer", "Summarise", "Report", "Escalate", "Plan"]
IMPERATIVE_RE = re.compile(r"^(\d\.\s*)?(" + "|".join(IMPERATIVES) + ")")
ACTION_Q = re.compile(r"\b(what should|recommend|action|fix|do we|should we|steps|how (do|should|to)|prepare|handle|escalat|treat)\b", re.I)


def _extractive(question: str, passages: list[dict], live: str | None) -> str:
    qt = set(tokenize(expand_abbreviations(question)))
    wants_actions = bool(ACTION_Q.search(question))
    findings, actions = [], []
    for p in passages:
        is_action_sec = any(a in p["section"].lower() for a in ACTION_SECTIONS)
        for s_ in _split_sentences(p["text"]):
            st = set(tokenize(expand_abbreviations(s_)))
            if not st:
                continue
            overlap = len(qt & st) / (len(qt) ** 0.5 + 1e-9)
            score = overlap + 0.35 / p["rank"]
            imperative = bool(IMPERATIVE_RE.match(s_))
            if wants_actions and (is_action_sec or imperative):
                actions.append((score + (0.3 if imperative else 0), p["rank"], re.sub(r"^\d\.\s*", "", s_)))
            else:
                findings.append((score, p["rank"], s_))
    findings.sort(key=lambda x: -x[0])
    actions.sort(key=lambda x: -x[0])

    def uniq(items, n):
        out, seen = [], set()
        for sc, r, s_ in items:
            if s_[:50] in seen:
                continue
            seen.add(s_[:50])
            out.append((r, s_.rstrip(".") + "."))
            if len(out) >= n:
                break
        return out

    lines = []
    if live:
        lines.append(f"Live data [L]: {live.splitlines()[0]}")
    top = uniq(findings, 2 if wants_actions else 4)
    if top:
        lines.append(" ".join(f"{s_} [{r}]" for r, s_ in top[:2]))
        for r, s_ in top[2:]:
            lines.append(f"- {s_} [{r}]")
    acts = uniq(actions, 5)
    if acts:
        lines.append("Recommended actions from the knowledge base:")
        lines += [f"{i}. {s_} [{r}]" for i, (r, s_) in enumerate(acts, 1)]
    if not top and not acts:
        lines.append("The knowledge base does not cover this question.")
    lines.append("(Extractive mode: quoted from the sources. Connect Claude or a local model in Settings for a written recommendation.)")
    return "\n".join(lines)


def provider_status() -> dict:
    s = config.LLMSettings()
    p = s.provider
    if p == "auto":
        p = "anthropic" if s.anthropic_key else ("ollama" if _ollama_up(s) else "extractive")
    model = s.anthropic_model if p == "anthropic" else s.ollama_model if p == "ollama" else "none (quotes sources)"
    return {"provider": p, "model": model, "configured": s.provider}


def answer(question: str, k: int = 5, doc_types: list[str] | None = None, live_context: str | None = None,
           provider: str | None = None) -> dict:
    t0 = time.time()
    passages = retrieve(question, k=k, doc_types=doc_types)
    s = config.LLMSettings()
    prov = provider or provider_status()["provider"]
    prompt = _prompt(question, passages, live_context)
    text, error = None, None
    try:
        if prov == "anthropic":
            text = _anthropic(prompt, s)
        elif prov == "ollama":
            text = _ollama(prompt, s)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        error = f"{prov} unavailable ({e.__class__.__name__}); fell back to extractive answer"
    if not text:
        prov_used = "extractive"
        text = _extractive(question, passages, live_context)
    else:
        prov_used = prov
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)})
    cites = [{"n": p["rank"], "doc_id": p["doc_id"], "title": p["title"], "section": p["section"], "score": p["score"],
              "cited": p["rank"] in cited} for p in passages]
    return {"question": question, "answer": text, "citations": cites, "passages": passages, "provider": prov_used,
            "model": s.anthropic_model if prov_used == "anthropic" else s.ollama_model if prov_used == "ollama" else None,
            "error": error, "latency_ms": int((time.time() - t0) * 1000), "prompt_chars": len(prompt)}


def recommend_for_incident(inc: dict) -> dict:
    """Turn an alert/incident into a question plus live context, then answer it."""
    kpi = inc.get("kpi_label", inc.get("kpi", ""))
    q = (f"{inc['queue_code']} {kpi} problem from {inc['start']} to {inc['end']}. Likely driver: {inc.get('likely_driver') or 'unknown'}. "
         f"What should operations and workforce management do, and which past RCA or SOP applies?")
    live = (f"Queue {inc['queue_code']}; {kpi}; period {inc['start']} to {inc['end']}; severity {inc['severity']}; "
            f"peak value {inc.get('peak_value')}; baseline or target {inc.get('baseline')}; likely driver {inc.get('likely_driver')}.\n"
            f"{inc.get('note') or ''}")
    return answer(q, live_context=live)
