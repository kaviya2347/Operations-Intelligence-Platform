"""Retrieval evaluation and the chunk-size experiment.

Each test question has the document(s) that should answer it. Metrics:
hit@1, hit@3 (is a correct document in the top k), MRR, and citation accuracy
(does the generated answer cite a correct document). Run for several chunk sizes
and three retrieval modes; the best chunk size is used for the production index.
"""
from __future__ import annotations

import numpy as np

from oip.copilot.answer import _extractive, retrieve
from oip.copilot.index import KBIndex

EVAL_SET = [
    ("What should the RTA do when service level is more than 10 points below target for two intervals?", ["SOP-WFM-01", "SOP-OPS-03"]),
    ("Who do we escalate to if abandon rate goes above 10% in an interval?", ["SOP-OPS-03"]),
    ("How are required agents calculated for chat queues?", ["SOP-WFM-02"]),
    ("What is planned shrinkage and how do we get scheduled heads from required agents?", ["SOP-WFM-02"]),
    ("Billing keeps breaching between 10 and 12 in the morning, what was the root cause?", ["RCA-2026-014"]),
    ("What did the Billing RCA recommend to fix the morning peak?", ["RCA-2026-014"]),
    ("Why did Meridian Cards handle time go up in April?", ["RCA-2026-011"]),
    ("Handle time has risen for every agent at once, what should we check first?", ["RCA-2026-011"]),
    ("Chat CSAT dropped after a mobile app release, what happened last time?", ["RCA-2026-009"]),
    ("How should agents handle a known issue on chat?", ["QA-02", "RCA-2026-009"]),
    ("When is the callback offer played to callers?", ["SOP-OPS-04"]),
    ("Are short abandons counted in service level?", ["SOP-OPS-04", "SLA-CLIENTS", "MET-01"]),
    ("How do we treat calls with extreme talk time from unclosed sessions?", ["SOP-DATA-05"]),
    ("What happens to answered calls where the agent was not captured?", ["SOP-DATA-05"]),
    ("Which disposition codes are allowed at wrap-up?", ["SOP-CRM-06"]),
    ("What is the target for after call work?", ["SOP-CRM-06"]),
    ("What are the quality audit parameters and their weights?", ["QA-01"]),
    ("What counts as a fatal error in a quality audit?", ["QA-01"]),
    ("How often should a customer on hold be updated?", ["QA-02"]),
    ("How is PII masked in the warehouse?", ["GOV-01"]),
    ("What can a team leader see on the dashboard?", ["GOV-01"]),
    ("What is the service level target for Meridian Cards and the penalty for missing it?", ["SLA-CLIENTS"]),
    ("What is the email service level for Halcyon policy servicing?", ["SLA-CLIENTS"]),
    ("How should we prepare for a Kestrel sale?", ["PLAYBOOK-KES-01"]),
    ("How big a forecast uplift should we use for order chats during a sale?", ["PLAYBOOK-KES-01"]),
    ("How is first contact resolution defined?", ["MET-01"]),
    ("What is the denominator for abandon rate?", ["MET-01"]),
    ("Which queue gets priority when several queues are at risk for overflow?", ["SOP-OPS-03"]),
    ("Before publishing a roster change what checks are required?", ["SOP-WFM-02"]),
    ("When should coaching sessions be scheduled?", ["QA-01", "SOP-WFM-01"]),
    ("What is the schedule adherence target?", ["SOP-WFM-01"]),
    ("Which agents are cross-skilled between Billing and Chat Care?", ["SOP-OPS-03"]),
]
CHUNK_SIZES = [80, 160, 320]
MODES = ["dense", "bm25", "hybrid"]


def evaluate(index: KBIndex, mode: str = "hybrid", k: int = 5) -> dict:
    hits1 = hits3 = 0
    rr, cite_ok, rows = [], 0, []
    for q, expected in EVAL_SET:
        res = retrieve(q, k=k, index=index, mode=mode)
        docs = [r["doc_id"] for r in res]
        ranks = [i + 1 for i, d in enumerate(docs) if d in expected]
        first = ranks[0] if ranks else None
        hits1 += first == 1
        hits3 += bool(first and first <= 3)
        rr.append(1 / first if first else 0)
        text = _extractive(q, res, None)
        import re
        cited = {res[int(n) - 1]["doc_id"] for n in re.findall(r"\[(\d+)\]", text) if int(n) <= len(res)}
        ok = bool(cited & set(expected))
        cite_ok += ok
        rows.append({"question": q, "expected": expected, "retrieved": docs, "first_correct_rank": first, "citation_correct": ok})
    n = len(EVAL_SET)
    return {"mode": mode, "chunk_words": index.chunk_words, "n": n, "hit_at_1": round(hits1 / n, 3), "hit_at_3": round(hits3 / n, 3),
            "mrr": round(float(np.mean(rr)), 3), "citation_accuracy": round(cite_ok / n, 3), "rows": rows}


def experiment() -> list[dict]:
    out = []
    for cw in CHUNK_SIZES:
        idx = KBIndex.build(cw)
        for m in MODES:
            r = evaluate(idx, m)
            out.append({k: v for k, v in r.items() if k != "rows"} | {"chunks": len(idx.chunks)})
    return out


def choose_chunk_size() -> int:
    res = [r for r in experiment() if r["mode"] == "hybrid"]
    best = max(res, key=lambda r: (r["hit_at_3"], r["mrr"], -abs(r["chunk_words"] - 160)))
    return best["chunk_words"]


def run_eval(verbose=True) -> dict:
    from oip.copilot.index import get_index
    grid = experiment()
    final = evaluate(get_index(), "hybrid")
    if verbose:
        for g in grid:
            print(f"  [rag-eval] chunk {g['chunk_words']:>3} words · {g['mode']:<6} hit@1 {g['hit_at_1']:.2f} hit@3 {g['hit_at_3']:.2f} "
                  f"MRR {g['mrr']:.2f} citation {g['citation_accuracy']:.2f}", flush=True)
        print(f"  [rag-eval] production index: hit@3 {final['hit_at_3']:.2f}, MRR {final['mrr']:.2f}, citation accuracy {final['citation_accuracy']:.2f}", flush=True)
    return {"grid": grid, "final": final}
