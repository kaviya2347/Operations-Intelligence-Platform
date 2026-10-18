"""Erlang C, root cause, forecasting and anomaly outputs."""
import math

import numpy as np
import pytest

from oip import artifacts
from oip.analytics.erlang import erlang_c, required_agents, service_level


def erlang_c_reference(n, a):
    top = a ** n / math.factorial(n) * n / (n - a)
    return top / (sum(a ** k / math.factorial(k) for k in range(n)) + top)


@pytest.mark.parametrize("n,a", [(11, 10.0), (5, 3.2), (20, 17.5), (2, 1.1)])
def test_erlang_c_matches_textbook_formula(n, a):
    assert float(erlang_c(n, a)[0]) == pytest.approx(erlang_c_reference(n, a), rel=1e-9)


def test_erlang_c_known_value():
    assert float(erlang_c(11, 10.0)[0]) == pytest.approx(0.6821, abs=1e-4)


def test_required_agents_meets_target_and_is_minimal():
    vol, aht, thr, tgt = np.array([120.0]), 300.0, 20, 0.8
    n = int(required_agents(vol, aht, thr, tgt)[0])
    load = vol[0] * aht / 1800
    assert service_level(n, load, aht, thr) >= tgt
    assert service_level(n - 1, load, aht, thr) < tgt


def test_rca_finds_billing_hotspots_and_staffing_cause():
    r = artifacts.load("rca")["Q01"]
    assert set(r["hotspots"]) & {"10:00", "10:30", "11:00", "11:30"}
    lead = max(r["hypotheses"], key=lambda h: h["primary_share_vital"])
    assert lead["hypothesis"] == "Staffing shortfall"
    assert r["change_point"]["significant"] and r["change_point"]["date"].startswith("2026-04")


def test_forecast_split_is_chronological_and_beats_baseline():
    f = artifacts.load("forecast")
    assert all(p["date"] >= f["test_start"] for p in f["predictions"])
    better = [r for r in f["results"] if r["models"][r["best_model"]]["mape"] < r["baseline_mape"]]
    assert len(better) == len(f["results"])


def test_planted_events_are_detected():
    inc = artifacts.load("anomalies")["incidents"]
    found = {(i["queue_code"], i["kpi"].split("_")[0]) for i in inc}
    assert ("NWT-BILL", "sl") in found
    assert any(i["queue_code"] == "KES-ORD" and i["kpi"] == "offered" for i in inc)
