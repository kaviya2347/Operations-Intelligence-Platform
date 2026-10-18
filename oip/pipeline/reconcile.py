"""Reconciliation: cleaned totals must agree with what the source systems reported.

Compares offered, answered and abandoned per queue per day against the dialler
and chat platform daily reports. Also replays the v1 'drop blank agent' rule to
show the variance that originally exposed it.
"""
from __future__ import annotations

import pandas as pd

from oip import db
from oip.reference import QUEUE_BY_ID


def reconcile(clean: pd.DataFrame, sample_dates: tuple[str, ...] = ("2026-03-16", "2026-04-14", "2026-05-11"), verbose=True) -> dict:
    src = db.read_sql("SELECT * FROM stg_source_daily_report")
    for c in ("offered", "answered", "abandoned"):
        src[c] = pd.to_numeric(src[c])
    rt = clean[clean.realtime].copy()
    rt["queue_code"] = rt.queue_id.map(lambda x: QUEUE_BY_ID[x].code)
    rt["date"] = rt.date.astype(str)

    def agg(frame):
        return frame.groupby(["date", "queue_code"]).agg(offered=("source_ref", "size"), answered=("handled", "sum"),
                                                         abandoned=("abandoned", "sum")).reset_index()

    cur = agg(rt)
    m = src.merge(cur, on=["date", "queue_code"], how="outer", suffixes=("_source", "_clean")).fillna(0)
    for c in ("offered", "answered", "abandoned"):
        m[f"{c}_variance"] = m[f"{c}_clean"] - m[f"{c}_source"]
    m["status"] = (m[["offered_variance", "answered_variance", "abandoned_variance"]].abs().sum(axis=1) == 0).map({True: "Match", False: "Variance"})

    v1 = agg(rt[~rt.agent_missing])                       # what the original rule produced
    m1 = src.merge(v1, on=["date", "queue_code"], how="outer", suffixes=("_source", "_clean")).fillna(0)
    m1["answered_variance"] = m1.answered_clean - m1.answered_source

    def sample(frame):
        f = frame[frame.date.isin(sample_dates)].groupby("date")[[c for c in frame.columns if c.endswith(("_source", "_clean", "_variance"))]].sum()
        return f.reset_index().to_dict("records")

    out = {
        "sample_dates": list(sample_dates),
        "current": {"rows": int(len(m)), "matched": int((m.status == "Match").sum()),
                    "total_offered_source": int(m.offered_source.sum()), "total_offered_clean": int(m.offered_clean.sum()),
                    "total_answered_source": int(m.answered_source.sum()), "total_answered_clean": int(m.answered_clean.sum()),
                    "by_sample_date": sample(m)},
        "v1_rule": {"description": "v1 dropped answered contacts with a blank agent_login",
                    "answered_variance_total": int(m1.answered_variance.sum()),
                    "by_sample_date": sample(m1.assign(offered_variance=0, abandoned_variance=0))},
        "detail": m.sort_values(["date", "queue_code"]).to_dict("records"),
    }
    if verbose:
        print(f"  [reconcile] {out['current']['matched']}/{out['current']['rows']} queue-days match source; "
              f"v1 rule would have lost {-out['v1_rule']['answered_variance_total']} answered contacts", flush=True)
    return out
