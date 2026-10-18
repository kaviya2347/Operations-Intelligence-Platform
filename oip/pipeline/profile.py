"""Data profiling for staging tables: the 'data quality worksheet'.

For every column: inferred type, null %, distinct count, top values or range.
Findings flag high missingness and label drift so cleaning rules can be agreed
before anything is changed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oip import db

PROFILE_TABLES = ["stg_dialler_calls", "stg_chat_sessions", "stg_email_tickets", "stg_backoffice_cases", "stg_crm_cases",
                  "stg_crm_case_status_history", "stg_csat_responses", "stg_qa_audits", "stg_wfm_plan",
                  "stg_wfm_staffed_interval", "stg_agent_sessions", "stg_hr_agents"]
SKIP = {"_batch_id", "_source_file", "_loaded_at"}


def _infer(s: pd.Series) -> str:
    nn = s.dropna()
    if nn.empty:
        return "empty"
    sample = nn.sample(min(500, len(nn)), random_state=0)
    if pd.to_numeric(sample, errors="coerce").notna().mean() > 0.97:
        return "numeric"
    if sample.astype(str).str.match(r"^\d{4}-\d{2}-\d{2}|^\d{2}/\d{2}/\d{4}").mean() > 0.9:
        return "datetime"
    return "text"


def profile_table(table: str) -> dict:
    df = db.read_sql(f"SELECT * FROM {table}")
    cols = []
    for c in df.columns:
        if c in SKIP:
            continue
        s = df[c]
        kind = _infer(s)
        info = {"column": c, "type": kind, "null_pct": round(float(s.isna().mean() * 100), 2), "distinct": int(s.nunique(dropna=True))}
        if kind == "numeric":
            x = pd.to_numeric(s, errors="coerce")
            info.update(min=float(np.nanmin(x)) if x.notna().any() else None, max=float(np.nanmax(x)) if x.notna().any() else None,
                        median=float(np.nanmedian(x)) if x.notna().any() else None, negatives=int((x < 0).sum()))
        elif kind == "datetime":
            iso = s.str.match(r"^\d{4}-\d{2}-\d{2}", na=False)
            info.update(alt_format_rows=int((~iso & s.notna()).sum()), min=str(s[iso].min()) if iso.any() else None,
                        max=str(s[iso].max()) if iso.any() else None)
        elif info["distinct"] <= 30:
            info["top"] = {str(k): int(v) for k, v in s.value_counts().head(8).items()}
        cols.append(info)
    dup_exact = int(df.drop(columns=[c for c in SKIP if c in df]).duplicated().sum())
    return {"table": table, "rows": int(len(df)), "columns": cols, "exact_duplicates": dup_exact}


def run_profile(verbose: bool = True) -> dict:
    tables = [profile_table(t) for t in PROFILE_TABLES]
    findings = []
    for t in tables:
        if t["exact_duplicates"]:
            findings.append({"table": t["table"], "column": "*", "severity": "high",
                             "finding": f"{t['exact_duplicates']:,} exact duplicate rows (likely ingestion re-run)"})
        for c in t["columns"]:
            if c["null_pct"] > 2 and c["column"] not in ("answer_time", "first_response_at", "agent_login", "logout_at"):
                findings.append({"table": t["table"], "column": c["column"], "severity": "medium",
                                 "finding": f"{c['null_pct']}% missing"})
            if c["column"] in ("queue_label", "mailbox", "workqueue") and c["distinct"] > 9:
                findings.append({"table": t["table"], "column": c["column"], "severity": "high",
                                 "finding": f"{c['distinct']} label variants for the same queues (label drift)"})
            if c["column"] == "disposition_label":
                findings.append({"table": t["table"], "column": c["column"], "severity": "high",
                                 "finding": f"{c['distinct']} spellings of 4 canonical outcomes; {c['null_pct']}% blank"})
            if c.get("negatives"):
                findings.append({"table": t["table"], "column": c["column"], "severity": "medium",
                                 "finding": f"{c['negatives']} negative values (clock skew)"})
            if c.get("alt_format_rows"):
                findings.append({"table": t["table"], "column": c["column"], "severity": "medium",
                                 "finding": f"{c['alt_format_rows']:,} timestamps in dd/mm/yyyy format without seconds"})
            if c["column"] == "score" and c.get("max") and c["max"] > 5:
                findings.append({"table": t["table"], "column": "score", "severity": "low", "finding": "scores outside the 1-5 scale"})
            if c["column"] == "talk_sec" and c.get("max", 0) > 7200:
                findings.append({"table": t["table"], "column": "talk_sec", "severity": "high",
                                 "finding": f"extreme values up to {c['max']:,.0f}s; investigate before treating"})
    out = {"tables": tables, "findings": findings}
    if verbose:
        print(f"  [profile] {len(tables)} tables profiled; {len(findings)} findings", flush=True)
    return out
