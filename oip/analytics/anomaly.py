"""KPI anomaly detection -> alerts.

For each queue and KPI, today's value is compared with a robust baseline (median
and MAD of the previous 28 days). Days beyond the threshold, in the harmful
direction, become alerts; consecutive alert days merge into one incident.
Known holidays are annotated instead of alerted for volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oip import db
from oip.reference import HOLIDAYS, QUEUE_BY_ID

KPIS = {  # id: (label, harmful direction, min absolute change to matter, unit)
    "sl": ("Service level", "down", 0.06, "pct"),
    "abandon_rate": ("Abandon rate", "up", 0.03, "pct"),
    "aht": ("Average handle time", "up", 30, "sec"),
    "offered": ("Volume", "both", 0.15, "rel"),
    "csat": ("CSAT", "down", 0.08, "pct"),
}
Z = 3.5


def daily_kpis() -> pd.DataFrame:
    d = db.read_sql("""SELECT c.queue_id, d.date,
           SUM(offered) offered, SUM(sl_num)*1.0/NULLIF(SUM(sl_den),0) sl,
           (SUM(abandoned)-SUM(short_abandoned))*1.0/NULLIF(SUM(rt_offered)-SUM(short_abandoned),0) abandon_rate,
           SUM(handle_sec)*1.0/NULLIF(SUM(handled),0) aht, SUM(csat_top2)*1.0/NULLIF(SUM(csat_resp),0) csat, SUM(csat_resp) csat_n,
           SUM(staffed_agents)*1.0/NULLIF(SUM(required_agents),0) staffing_ratio, SUM(forecast_volume) forecast
        FROM rpt_interval_cube c JOIN dim_date d USING(date_key) GROUP BY c.queue_id, d.date ORDER BY c.queue_id, d.date""")
    d["date"] = pd.to_datetime(d.date)
    return d


def hotspot_incidents(rca: dict) -> list[dict]:
    """Recurring interval hotspots found by RCA become alerts: structural problems a daily z-score misses."""
    out = []
    for qid, r in (rca or {}).items():
        if not r.get("hotspots"):
            continue
        cp = r.get("change_point") or {}
        start = cp.get("date") if cp.get("significant") else r["range"]["start"]
        lead = max(r.get("attribution_vital", {}).items(), key=lambda kv: kv[1], default=("Unknown", 0))
        out.append({"incident_id": f"INC-{r['queue_code']}-{start[5:7]}{start[8:10]}-hotspot", "queue_id": qid, "queue_code": r["queue_code"],
                    "kpi": "sl_hotspot", "kpi_label": "Service level: recurring hotspot", "start": start, "end": r["range"]["end"],
                    "days": None, "severity": "critical", "peak_value": None, "baseline": r["target"], "peak_z": None,
                    "likely_driver": lead[0], "note": f"Intervals {', '.join(sorted(r['hotspots']))} breach repeatedly; " + (r["summary"][3] if len(r["summary"]) > 3 else "")})
    return out


def run_anomaly(verbose=True, rca: dict | None = None) -> dict:
    d = daily_kpis()
    hol = {pd.Timestamp(k): v[0] for k, v in HOLIDAYS.items()}
    alerts = []
    for qid, g in d.groupby("queue_id"):
        g = g.sort_values("date").reset_index(drop=True)
        q = QUEUE_BY_ID[qid]
        for k, (label, direction, min_abs, unit) in KPIS.items():
            if k == "abandon_rate" and not q.realtime:
                continue
            x = g[k].astype(float)
            if k == "csat":
                x = x.where(g.csat_n >= 15)        # too few responses to judge
            if unit == "rel":
                # volume has strong weekly seasonality: baseline is the same weekday over the previous 4 weeks
                wd = g.date.dt.dayofweek
                base = x.groupby(wd).transform(lambda s: s.shift(1).rolling(4, min_periods=2).median())
                ratio = x / base - 1
                rb = ratio.shift(1).rolling(28, min_periods=14).median()
                rmad = ((ratio.shift(1) - rb).abs().rolling(28, min_periods=7).median() * 1.4826).clip(lower=0.03)
                z = (ratio - rb) / rmad
            else:
                base = x.shift(1).rolling(28, min_periods=14).median()
                mad = (x.shift(1) - base).abs().rolling(28, min_periods=7).median() * 1.4826
                mad = mad.clip(lower={"pct": 0.01, "sec": 5}[unit])
                z = (x - base) / mad
            for i in np.flatnonzero(z.notna().values):
                zi, xi, bi = float(z.iloc[i]), float(x.iloc[i]), float(base.iloc[i])
                change = xi - bi
                if unit == "rel":
                    rel = change / bi if bi else 0
                    hit = abs(zi) >= Z and abs(rel) >= min_abs
                else:
                    hit = abs(zi) >= Z and abs(change) >= min_abs
                harmful = direction == "both" or (direction == "down" and zi < 0) or (direction == "up" and zi > 0)
                if not (hit and harmful):
                    continue
                day = g.date.iloc[i]
                note = None
                if k == "offered" and day in hol:
                    note = f"Public holiday ({hol[day]}): expected dip"
                below_target = (k == "sl" and xi < q.sl_target) or (k == "abandon_rate" and xi > q.abandon_target)
                sev = "critical" if abs(zi) >= 6 or (below_target and abs(zi) >= 4.5) else "high" if abs(zi) >= 4.5 or below_target else "medium"
                alerts.append({"queue_id": qid, "queue_code": q.code, "date": day.strftime("%Y-%m-%d"), "kpi": k, "kpi_label": label,
                               "value": round(xi, 4), "baseline": round(bi, 4), "z": round(zi, 2), "severity": sev if not note else "info",
                               "note": note, "staffing_ratio": round(float(g.staffing_ratio.iloc[i]), 3) if pd.notna(g.staffing_ratio.iloc[i]) else None,
                               "volume_vs_forecast": round(float(g.offered.iloc[i] / g.forecast.iloc[i]), 3) if g.forecast.iloc[i] else None})
        # sustained shifts: 7-day mean vs the 28 days before it (catches level changes a daily z-score adapts to)
        for k, (label, direction, min_abs, unit) in (("sl", KPIS["sl"]), ("abandon_rate", KPIS["abandon_rate"])):
            if k == "abandon_rate" and not q.realtime:
                continue
            x = g[k].astype(float)
            recent = x.rolling(7).mean()
            prior = x.shift(7).rolling(28, min_periods=21).mean()
            sd = x.shift(7).rolling(28, min_periods=21).std()
            t = (recent - prior) / (sd / np.sqrt(7))
            bad = (t <= -4) & (prior - recent >= 0.04) if direction == "down" else (t >= 4) & (recent - prior >= 0.02)
            idx = np.flatnonzero(bad.fillna(False).values)
            if len(idx):
                i = idx[0]
                day = g.date.iloc[i]
                alerts.append({"queue_id": qid, "queue_code": q.code, "date": day.strftime("%Y-%m-%d"), "kpi": k + "_shift",
                               "kpi_label": f"{label}: sustained shift", "value": round(float(recent.iloc[i]), 4), "baseline": round(float(prior.iloc[i]), 4),
                               "z": round(float(t.iloc[i]), 2), "severity": "critical",
                               "note": f"7-day average {g.date.iloc[max(i - 6, 0)]:%d %b}-{day:%d %b} moved away from the previous 4 weeks",
                               "staffing_ratio": round(float(g.staffing_ratio.iloc[max(i - 6, 0):i + 1].mean()), 3),
                               "volume_vs_forecast": round(float(g.offered.iloc[max(i - 6, 0):i + 1].sum() / g.forecast.iloc[max(i - 6, 0):i + 1].sum()), 3)})
    a = pd.DataFrame(alerts)
    incidents = []
    if len(a):
        a = a.sort_values(["queue_id", "kpi", "date"])
        a["d"] = pd.to_datetime(a.date)
        a["grp"] = (a.groupby(["queue_id", "kpi"]).d.diff().dt.days.fillna(99) > 3).cumsum()
        for _, g in a.groupby("grp"):
            worst = g.loc[g.z.abs().idxmax()]
            sev_rank = {"critical": 3, "high": 2, "medium": 1, "info": 0}
            hint = None
            sr, vf = worst.staffing_ratio, worst.volume_vs_forecast
            if worst.kpi in ("sl", "abandon_rate", "sl_shift", "abandon_rate_shift"):
                if sr is not None and sr < 0.92:
                    hint = "Staffing below requirement"
                elif vf is not None and vf > 1.12:
                    hint = "Volume above forecast"
            if worst.kpi == "aht":
                hint = "Handle time above baseline (check systems and process changes)"
            incidents.append({"incident_id": f"INC-{worst.queue_code}-{g.d.min():%m%d}-{worst.kpi}", "queue_id": worst.queue_id,
                              "queue_code": worst.queue_code, "kpi": worst.kpi, "kpi_label": worst.kpi_label,
                              "start": g.d.min().strftime("%Y-%m-%d"), "end": g.d.max().strftime("%Y-%m-%d"), "days": int(len(g)),
                              "severity": max(g.severity, key=lambda s: sev_rank[s]), "peak_value": worst.value, "baseline": worst.baseline,
                              "peak_z": worst.z, "likely_driver": hint, "note": worst.note if isinstance(worst.note, str) else None})
        a = a.drop(columns=["d", "grp"])
    incidents = hotspot_incidents(rca) + incidents
    inc = sorted(incidents, key=lambda x: ({"critical": 0, "high": 1, "medium": 2, "info": 3}[x["severity"]], x["start"]))
    if verbose:
        print(f"  [anomaly] {len(alerts)} alert-days merged into {len(inc)} incidents", flush=True)
    return {"method": f"Robust z-score vs 28-day rolling median/MAD, |z| >= {Z}, harmful direction only", "alerts": a.to_dict("records") if len(a) else [],
            "incidents": inc}
