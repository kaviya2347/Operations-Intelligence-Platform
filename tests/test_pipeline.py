"""Cleaning rules, reconciliation and PII handling."""
import re

from oip import artifacts, db
from oip.reference import QUEUES


def test_no_duplicate_business_keys():
    d = db.read_sql("SELECT source_system, source_ref, start_ts, COUNT(*) n FROM fact_interaction GROUP BY 1, 2, 3 HAVING n > 1")
    assert d.empty


def test_queue_labels_are_canonical():
    ids = set(db.read_sql("SELECT DISTINCT queue_id FROM fact_interaction").queue_id)
    assert ids <= {q.queue_id for q in QUEUES}


def test_no_negative_waits_or_handle_times():
    assert db.read_sql("SELECT COUNT(*) n FROM fact_interaction WHERE wait_sec < 0 OR handle_sec < 0").n[0] == 0


def test_answered_rows_without_agent_are_kept_and_flagged():
    d = db.read_sql("SELECT COUNT(*) n FROM fact_interaction WHERE handled = 1 AND agent_missing = 1").iloc[0]
    assert d.n > 0


def test_unclosed_sessions_capped_long_calls_kept():
    log = artifacts.load("cleaning_log")
    o = log["outliers"]
    assert o["capped"] > 0 and o["kept_long"] > 0
    assert o["max_after"] < o["max_before"]


def test_reconciliation_matches_source_and_catches_v1_bug():
    r = artifacts.load("reconciliation")
    assert r["current"]["matched"] == r["current"]["rows"]
    assert r["current"]["total_answered_clean"] == r["current"]["total_answered_source"]
    assert r["v1_rule"]["answered_variance_total"] < 0


def test_cleaning_log_is_complete():
    steps = artifacts.load("cleaning_log")["steps"]
    assert [s["rule_id"] for s in steps] == [f"R{i:02d}" for i in range(len(steps))]


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\b\d{10}\b|\+\d{6,}")


def test_no_clear_pii_in_warehouse():
    for table in ("dim_customer", "fact_interaction"):
        df = db.read_sql(f"SELECT * FROM {table} LIMIT 5000")
        text = [str(x) for x in df.select_dtypes(include=["object", "string"]).to_numpy().ravel() if x is not None]
        assert not any(EMAIL.search(t) for t in text), table
        assert not any(PHONE.search(t) for t in text), table
