"""Access control, SQL guard rails and the copilot."""
import pytest

from oip import artifacts
from oip.api.sql_lab import SQLError, check


def H(u):
    return {"X-OIP-User": u}


def test_row_level_security_limits_queues(client):
    cube = client.get("/api/cube", headers=H("tl-billing")).json()
    assert set(cube["data"]["queue_id"]) == {"Q01"}


def test_client_viewer_cannot_open_other_queue(client):
    assert client.get("/api/rca?queue=Q01", headers=H("client-meridian")).status_code == 403


def test_client_viewer_sees_masked_agent_names(client):
    agents = client.get("/api/agents", headers=H("client-meridian")).json()["agents"]
    assert agents and all(a["full_name"].startswith("Agent ") for a in agents)


def test_quality_and_sql_restricted_to_analysts(client):
    assert client.get("/api/quality", headers=H("tl-billing")).status_code == 403
    assert client.post("/api/sql", json={"sql": "SELECT 1"}, headers=H("tl-billing")).status_code == 403


@pytest.mark.parametrize("sql", ["DROP TABLE dim_date", "SELECT 1; SELECT 2", "SELECT * FROM stg_dialler_calls",
                                 "UPDATE dim_queue SET name = 'x'", "PRAGMA table_info(dim_date)", "ATTACH 'x.db' AS x"])
def test_sql_guard_blocks(sql):
    with pytest.raises(SQLError):
        check(sql)


def test_sql_lab_runs_select_with_plan(client):
    r = client.post("/api/sql", json={"sql": "SELECT queue_id, COUNT(*) n FROM fact_interaction WHERE date_key BETWEEN 20260501 AND 20260507 GROUP BY 1"},
                    headers=H("analyst")).json()
    assert r["row_count"] > 0 and r["plan"]


def test_index_review_slow_query_scans_fast_query_searches(client):
    from oip.api.sql_lab import SAVED
    q = {s["id"]: s["sql"] for s in SAVED}
    slow = client.post("/api/sql", json={"sql": q["slow-query"]}, headers=H("analyst")).json()["plan"]
    fast = client.post("/api/sql", json={"sql": q["fast-query"]}, headers=H("analyst")).json()["plan"]
    assert any(p.startswith("SCAN") and "fact_interaction" in p for p in slow)
    assert any(p.startswith("SEARCH") for p in fast)


def test_saved_queries_all_run(client):
    from oip.api.sql_lab import SAVED
    for s in SAVED:
        r = client.post("/api/sql", json={"sql": s["sql"]}, headers=H("analyst")).json()
        assert "error" not in r, s["id"]


def test_retrieval_quality_threshold():
    e = artifacts.load("rag_eval")["final"]
    assert e["hit_at_3"] >= 0.9 and e["mrr"] >= 0.8 and e["citation_accuracy"] >= 0.9


def test_copilot_answer_has_citations(client):
    r = client.post("/api/copilot/ask", json={"question": "Are short abandons counted in service level?"}).json()
    assert r["passages"] and any(c["cited"] for c in r["citations"])
    assert r["passages"][0]["doc_id"] in {"MET-01", "SOP-OPS-04", "SLA-CLIENTS"}
