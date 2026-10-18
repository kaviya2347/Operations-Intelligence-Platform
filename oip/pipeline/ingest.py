"""Ingestion: landing-zone extracts -> staging tables, with PII masked on the way in.

Governance rules applied here (see docs/governance.md and KB GOV-01):
  * Customer identifiers (phone, email, name) never enter staging in clear text.
    Each is replaced by a salted SHA-256 key (for joining) and a masked display
    value (for support teams), e.g. 98XXXXXX21, a***@gmail.com, A. K.
  * Every load is recorded in gov_load_log with row counts and a file checksum.
  * gov_pii_register lists every sensitive column and the treatment applied.
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid

import numpy as np
import pandas as pd

from oip import config, db

SALT = os.environ.get("OIP_HASH_SALT", "oip-demo-salt")

PII_REGISTER = [
    # table, column, classification, treatment
    ("dialler_calls", "ani", "Customer phone (PII)", "hashed to ani_key; masked to ani_masked"),
    ("chat_sessions", "visitor_email", "Customer email (PII)", "hashed to email_key; masked to email_masked"),
    ("email_tickets", "from_address", "Customer email (PII)", "hashed to email_key; masked to email_masked"),
    ("backoffice_cases", "customer_phone", "Customer phone (PII)", "hashed to phone_key; masked to phone_masked"),
    ("crm_customers", "full_name", "Customer name (PII)", "masked to initials; clear value dropped"),
    ("crm_customers", "phone", "Customer phone (PII)", "hashed + masked"),
    ("crm_customers", "email", "Customer email (PII)", "hashed + masked"),
    ("hr_agents", "full_name", "Employee name (internal)", "kept; visible to Admin and Team Leader roles only"),
]


def hash_series(s: pd.Series) -> pd.Series:
    vals = s.fillna("").astype(str).str.strip().str.lower().values
    out = np.array([hashlib.sha256((SALT + v).encode()).hexdigest()[:16] if v else None for v in vals], dtype=object)
    return pd.Series(out, index=s.index)


def mask_phone(s: pd.Series) -> pd.Series:
    s = s.fillna("").astype(str).str.replace(r"\D", "", regex=True)
    return (s.str[:2] + "XXXXXX" + s.str[-2:]).where(s.str.len() >= 6, None)


def mask_email(s: pd.Series) -> pd.Series:
    s = s.fillna("").astype(str)
    user = s.str.split("@").str[0]
    dom = s.str.split("@").str[1]
    return (user.str[:1] + "***@" + dom).where(s.str.contains("@"), None)


def mask_name(s: pd.Series) -> pd.Series:
    parts = s.fillna("").astype(str).str.split()
    return parts.apply(lambda p: " ".join(x[0] + "." for x in p) if p else None)


def _checksum(path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(config.RAW_DIR / f"{name}.csv", dtype=str, keep_default_na=False, na_values=[""])


def ingest(verbose: bool = True) -> dict:
    t0 = time.time()
    batch = uuid.uuid4().hex[:12]
    loaded_at = pd.Timestamp.now().isoformat(timespec="seconds")
    log = []

    def stage(name: str, df: pd.DataFrame):
        df = df.copy()
        df["_batch_id"] = batch
        df["_source_file"] = f"{name}.csv"
        df["_loaded_at"] = loaded_at
        n = db.write(df, f"stg_{name}")
        log.append({"batch_id": batch, "table": f"stg_{name}", "source_file": f"{name}.csv", "rows": n,
                    "checksum": _checksum(config.RAW_DIR / f"{name}.csv"), "loaded_at": loaded_at})
        if verbose:
            print(f"  [ingest] stg_{name:<28} {n:>9,} rows", flush=True)

    d = _read("dialler_calls")
    d["ani_key"], d["ani_masked"] = hash_series(d.ani), mask_phone(d.ani)
    stage("dialler_calls", d.drop(columns=["ani"]))

    c = _read("chat_sessions")
    c["email_key"], c["email_masked"] = hash_series(c.visitor_email), mask_email(c.visitor_email)
    stage("chat_sessions", c.drop(columns=["visitor_email"]))

    e = _read("email_tickets")
    e["email_key"], e["email_masked"] = hash_series(e.from_address), mask_email(e.from_address)
    stage("email_tickets", e.drop(columns=["from_address"]))

    b = _read("backoffice_cases")
    b["phone_key"], b["phone_masked"] = hash_series(b.customer_phone), mask_phone(b.customer_phone)
    stage("backoffice_cases", b.drop(columns=["customer_phone"]))

    cu = _read("crm_customers")
    cu["name_masked"] = mask_name(cu.full_name)
    cu["phone_key"], cu["phone_masked"] = hash_series(cu.phone), mask_phone(cu.phone)
    cu["email_key"], cu["email_masked"] = hash_series(cu.email), mask_email(cu.email)
    stage("crm_customers", cu.drop(columns=["full_name", "phone", "email"]))

    for name in ("crm_cases", "crm_case_status_history", "csat_responses", "qa_audits", "wfm_plan",
                 "wfm_staffed_interval", "agent_sessions", "hr_agents", "source_daily_report", "holidays"):
        stage(name, _read(name))

    db.write(pd.DataFrame(log), "gov_load_log", if_exists="append")
    db.write(pd.DataFrame(PII_REGISTER, columns=["source_table", "column_name", "classification", "treatment"]), "gov_pii_register")
    if verbose:
        print(f"  [ingest] batch {batch} loaded in {time.time() - t0:.1f}s; PII masked at entry", flush=True)
    return {"batch_id": batch, "tables": len(log), "rows": int(sum(x["rows"] for x in log))}
