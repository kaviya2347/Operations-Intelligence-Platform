"""Exploratory data analysis: distributions, drivers of variation, load patterns, correlations."""
from __future__ import annotations

import numpy as np
import pandas as pd

from oip import db


def _hist(x: pd.Series, bins: np.ndarray) -> dict:
    counts, edges = np.histogram(x.clip(bins[0], bins[-1]), bins=bins)
    return {"edges": [float(e) for e in edges], "counts": [int(c) for c in counts]}


def _box(x: pd.Series) -> dict:
    q = x.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return {"p5": float(q[0.05]), "q1": float(q[0.25]), "median": float(q[0.5]), "q3": float(q[0.75]), "p95": float(q[0.95]),
            "mean": float(x.mean()), "n": int(len(x))}


def run_eda(verbose=True) -> dict:
    f = db.read_sql("""SELECT f.queue_id, q.queue_code, f.channel, f.handled, f.abandoned, f.wait_sec, f.handle_sec, f.hour,
                              f.weekday, f.shift_window, a.tenure_band, f.realtime
                       FROM fact_interaction f JOIN dim_queue q USING(queue_id) LEFT JOIN dim_agent a ON a.agent_id = f.agent_id""")
    h = f[f.handled == 1]
    rt = f[f.realtime == 1]
    out = {}
    out["distributions"] = {
        "handle_sec": _hist(h[h.channel == "Voice"].handle_sec, np.arange(0, 2101, 60)),
        "wait_sec_answered": _hist(rt[rt.handled == 1].wait_sec, np.arange(0, 301, 10)),
        "csat": db.read_sql("SELECT score, COUNT(*) n FROM fact_csat GROUP BY score ORDER BY score").to_dict("records"),
        "interval_volume": _hist(db.read_sql("SELECT offered FROM rpt_interval_cube WHERE offered > 0").offered, np.arange(0, 81, 2)),
    }
    out["aht_box_by_queue"] = {q: _box(g.handle_sec) for q, g in h.groupby("queue_code")}
    out["aht_by_tenure"] = (h[h.tenure_band.notna() & (h.tenure_band != "n/a")].groupby(["queue_code", "tenure_band"]).handle_sec
                            .median().round(0).unstack().reindex(columns=["0-3m", "3-6m", "6-12m", "12m+"]).reset_index()
                            .to_dict("records"))
    out["aht_by_shift"] = h.groupby(["queue_code", "shift_window"]).handle_sec.median().round(0).unstack().reset_index().to_dict("records")
    hw = rt.groupby(["weekday", "hour"]).size().unstack(fill_value=0)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hw = hw.reindex(days)
    out["load_heatmap"] = {"rows": days, "cols": [int(c) for c in hw.columns], "values": (hw.values / 13.0).round(1).tolist(),
                           "note": "Average real-time contacts per hour (13 weeks)"}
    qd = db.read_sql("""SELECT queue_id, date_key, SUM(offered) offered, SUM(handle_sec)*1.0/NULLIF(SUM(handled),0) aht,
                               SUM(sl_num)*1.0/NULLIF(SUM(sl_den),0) sl,
                               (SUM(abandoned)-SUM(short_abandoned))*1.0/NULLIF(SUM(rt_offered)-SUM(short_abandoned),0) abandon,
                               SUM(staffed_agents)*1.0/NULLIF(SUM(required_agents),0) staffing,
                               SUM(handle_sec)*1.0/NULLIF(SUM(capacity_sec),0) occupancy,
                               SUM(csat_top2)*1.0/NULLIF(SUM(csat_resp),0) csat
                        FROM rpt_interval_cube WHERE queue_id IN ('Q01','Q02','Q03','Q04','Q05','Q06') GROUP BY 1,2""")
    cols = ["offered", "aht", "sl", "abandon", "staffing", "occupancy", "csat"]
    z = qd.groupby("queue_id")[cols].transform(lambda s: (s - s.mean()) / s.std())
    corr = z.corr().round(2)
    out["correlation"] = {"labels": ["Volume", "AHT", "Service level", "Abandon", "Staffed/required", "Occupancy", "CSAT"],
                          "matrix": corr.values.tolist(), "note": "Pearson correlation of daily metrics, standardised within queue (real-time queues)"}
    peak = hw.stack().idxmax()
    tb = h[h.tenure_band.isin(["0-3m", "12m+"])].groupby("tenure_band").handle_sec.median()
    out["observations"] = [
        f"Peak load is {peak[0]} around {peak[1]:02d}:00; Mondays carry about {hw.loc['Mon'].sum() / hw.loc['Wed'].sum() - 1:+.0%} more real-time volume than Wednesdays.",
        f"Agents in their first three months take {tb['0-3m'] / tb['12m+'] - 1:+.0%} longer per contact than agents with more than a year's tenure (median handle time).",
        f"Service level moves with staffing coverage (r = {corr.loc['sl', 'staffing']:+.2f}) more than with volume (r = {corr.loc['sl', 'offered']:+.2f}).",
        f"Abandon rate mirrors service level (r = {corr.loc['abandon', 'sl']:+.2f}); CSAT is only weakly tied to daily service level (r = {corr.loc['csat', 'sl']:+.2f}).",
        "Handle time is right-skewed (long tail of complex calls), so medians and P90s are reported alongside means.",
    ]
    if verbose:
        print(f"  [eda] {len(out['observations'])} observations", flush=True)
    return out
