"""Root-cause analysis for service-level breaches.

Method (mirrors the SLA-breach RCA done with the operations team):
  1. Define a breach: an interval whose service level is below the queue target
     with enough contacts to be meaningful (sl_den >= min_offered).
  2. Pareto: which half-hour intervals produce most breaches ("vital few").
  3. Segment by weekday, shift window and week; find the date the breach rate changed.
  4. Test candidate causes on breach vs non-breach intervals:
       staffing shortfall  (staffed / required)
       volume spike        (actual / forecast volume)
       AHT inflation       (actual / forecast handle time)
     with effect sizes, Mann-Whitney U tests and a primary-cause attribution per breach.
  5. Quantify the staffing gap in the vital-few intervals and estimate, with
     Erlang C, what service level would have been at the required staffing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import binomtest, mannwhitneyu

from oip import config, db
from oip.analytics.erlang import service_level
from oip.reference import QUEUE_BY_ID


def _load(queue_id: str, start: str | None, end: str | None) -> pd.DataFrame:
    where = ["c.queue_id = :q"]
    params = {"q": queue_id}
    if start:
        where.append("c.date_key >= :s"); params["s"] = int(start.replace("-", ""))
    if end:
        where.append("c.date_key <= :e"); params["e"] = int(end.replace("-", ""))
    return db.read_sql(f"""SELECT c.*, i.label, i.shift_window, d.date, d.weekday, d.weekday_num, d.iso_week, d.is_holiday
                           FROM rpt_interval_cube c JOIN dim_interval i USING(interval_idx) JOIN dim_date d USING(date_key)
                           WHERE {' AND '.join(where)} ORDER BY c.date_key, c.interval_idx""", params)


def _verdict(share, p, effect_ok):
    if share >= 0.40 and p < 0.01 and effect_ok:
        return "Supported"
    if share >= 0.15 and effect_ok:
        return "Partly supported"
    return "Not supported"


def change_point(daily: pd.Series) -> dict | None:
    """Single change point in the mean of a daily series (max between-segment difference, min 10 days each side)."""
    x = daily.values.astype(float)
    n = len(x)
    if n < 25:
        return None
    best = None
    for k in range(10, n - 10):
        a, b = x[:k], x[k:]
        pooled = np.sqrt((a.var(ddof=1) / len(a)) + (b.var(ddof=1) / len(b))) or 1e-9
        t = (b.mean() - a.mean()) / pooled
        if best is None or abs(t) > abs(best[1]):
            best = (k, t, a.mean(), b.mean())
    k, t, ma, mb = best
    return {"date": str(daily.index[k]), "before": round(float(ma), 4), "after": round(float(mb), 4), "t_stat": round(float(t), 2),
            "significant": bool(abs(t) > 4)}


def run_rca(queue_id: str = "Q01", start: str | None = None, end: str | None = None, min_offered: int = 5) -> dict:
    q = QUEUE_BY_ID[queue_id]
    c = _load(queue_id, start, end)
    c["sl"] = c.sl_num / c.sl_den.replace(0, np.nan)
    c["eligible"] = c.sl_den >= min_offered
    # A raw miss is any interval under target. A breach is a miss larger than random variation at that volume:
    # SL below target by more than 1.645 binomial standard errors (one-sided 95%).
    se = np.sqrt(q.sl_target * (1 - q.sl_target) / c.sl_den.clip(lower=1))
    c["miss"] = c.eligible & (c.sl < q.sl_target)
    c["breach"] = c.eligible & (c.sl < q.sl_target - 1.645 * se)
    e = c[c.eligible].copy()
    if e.empty:
        return {"queue_id": queue_id, "error": "No intervals with enough volume in this range."}

    # ratios for hypothesis tests
    e["staff_ratio"] = e.staffed_agents / e.required_agents.replace(0, np.nan)
    e["vol_ratio"] = e.offered / e.forecast_volume.replace(0, np.nan)
    fc_aht = e.fc_aht_x_vol / e.forecast_volume.replace(0, np.nan)
    e["aht_ratio"] = (e.handle_sec / e.handled.replace(0, np.nan)) / fc_aht

    # 2. Pareto by interval
    par = e.groupby("label").agg(breaches=("breach", "sum"), intervals=("breach", "size"),
                                 sl=("sl_num", "sum"), den=("sl_den", "sum")).reset_index()
    par["breach_rate"] = par.breaches / par.intervals
    par["sl"] = par.sl / par.den
    par = par.sort_values("breaches", ascending=False).reset_index(drop=True)
    total_b = int(par.breaches.sum())
    par["cum_share"] = par.breaches.cumsum() / max(total_b, 1)
    vital = par[(par.cum_share.shift(fill_value=0) < 0.8) & (par.breaches > 0)]
    base_rate = total_b / len(e)
    # hotspots: intervals whose breach rate is significantly above the queue's own baseline (binomial, p < 0.001)
    par["p_hotspot"] = [binomtest(int(r.breaches), int(r.intervals), base_rate, alternative="greater").pvalue if r.intervals else 1.0
                        for r in par.itertuples()]
    par["hotspot"] = (par.p_hotspot < 0.001) & (par.breach_rate >= 2 * base_rate)
    hotspots = par[par.hotspot].label.tolist()
    vital_labels = hotspots if hotspots else vital.label.tolist()

    # 3. segmentation and change point
    seg_wd = e.groupby(["weekday_num", "weekday"]).agg(breaches=("breach", "sum"), intervals=("breach", "size")).reset_index()
    seg_wd["breach_rate"] = seg_wd.breaches / seg_wd.intervals
    seg_sh = e.groupby("shift_window").agg(breaches=("breach", "sum"), intervals=("breach", "size")).reset_index()
    seg_sh["breach_rate"] = seg_sh.breaches / seg_sh.intervals
    weekly = e.groupby("iso_week").agg(week_start=("date", "min"), breaches=("breach", "sum"), intervals=("breach", "size"),
                                       sl_num=("sl_num", "sum"), sl_den=("sl_den", "sum")).reset_index()
    weekly["breach_rate"] = weekly.breaches / weekly.intervals
    weekly["sl"] = weekly.sl_num / weekly.sl_den

    # 4. hypotheses: distribution tests on breach vs non-breach intervals
    b, nb = e[e.breach], e[~e.breach]
    e["vol_z"] = (e.offered - e.forecast_volume) / np.sqrt(e.forecast_volume.clip(lower=1))   # Poisson-scaled surprise
    b, nb = e[e.breach], e[~e.breach]
    tests = []
    for key, col, label, thr, direction, desc in (
        ("staffing", "staff_ratio", "Staffing shortfall", 0.9, "lower", "Staffed agents at least 10% below what the forecast required"),
        ("volume", "vol_z", "Volume spike", 2.0, "higher", "Actual volume more than two standard deviations above forecast"),
        ("aht", "aht_ratio", "Handle-time inflation", 1.15, "higher", "Actual handle time at least 15% above the planning AHT"),
    ):
        xb, xn = b[col].dropna(), nb[col].dropna()
        if len(xb) < 3 or len(xn) < 3:
            continue
        p = mannwhitneyu(xb, xn, alternative="less" if direction == "lower" else "greater").pvalue
        share = float(((xb < thr) if direction == "lower" else (xb > thr)).mean())
        share_nb = float(((xn < thr) if direction == "lower" else (xn > thr)).mean())
        effect_ok = (xb.median() < xn.median()) if direction == "lower" else (xb.median() > xn.median())
        tests.append({"key": key, "hypothesis": label, "description": desc, "metric": col,
                      "threshold": thr, "median_breach": round(float(xb.median()), 3), "median_ok": round(float(xn.median()), 3),
                      "share_breach_beyond": round(share, 3), "share_ok_beyond": round(share_nb, 3),
                      "p_value": float(f"{p:.2e}"), "verdict": None, "effect_ok": bool(effect_ok)})

    # Shapley attribution on an Erlang C model: for each interval, evaluate service level with every
    # combination of {staffing, volume, handle time} reset to plan and split the gap fairly between causes.
    aht_act = (e.handle_sec / e.handled.replace(0, np.nan)).fillna(q.base_aht_sec).values
    fc_aht_e = (e.fc_aht_x_vol / e.forecast_volume.replace(0, np.nan)).fillna(q.base_aht_sec).values
    conc = q.concurrency
    actual = {"S": e.staffed_agents.values.astype(float), "V": e.offered.values.astype(float), "A": aht_act}
    plan = {"S": np.maximum(e.required_agents.values, 1).astype(float), "V": e.forecast_volume.values, "A": fc_aht_e}

    def _sl(fixed):
        n = plan["S"] if "S" in fixed else actual["S"]
        v = plan["V"] if "V" in fixed else actual["V"]
        a = plan["A"] if "A" in fixed else actual["A"]
        return service_level(np.maximum(n, 0.01) * conc, v * a / 1800, a, q.sl_threshold_sec)

    names = {"S": "Staffing shortfall", "V": "Volume spike", "A": "Handle-time inflation"}
    if q.realtime:
        from itertools import combinations
        sl_cache = {frozenset(c): _sl(set(c)) for r in range(4) for c in combinations("SVA", r)}
        w = {0: 1 / 3, 1: 1 / 6, 2: 1 / 3}
        shap = {}
        for f in "SVA":
            others = [x for x in "SVA" if x != f]
            val = np.zeros(len(e))
            for r in range(3):
                for c in combinations(others, r):
                    val += w[r] * (sl_cache[frozenset(c) | {f}] - sl_cache[frozenset(c)])
            shap[names[f]] = val
        sh = pd.DataFrame(shap, index=e.index)
        pos = sh.clip(lower=0)
        e["primary_cause"] = pos.idxmax(axis=1).where(pos.max(axis=1) >= 0.03, "Random variation")
        for col in sh:
            e[f"shap_{col}"] = sh[col]
        fix_staff = sl_cache[frozenset("S")]
        base_m = sl_cache[frozenset()]
    else:
        e["primary_cause"] = "Backlog (asynchronous queue)"

    b = e[e.breach]
    attribution = b.primary_cause.value_counts(normalize=True).round(3).to_dict()
    vb = b[b.label.isin(vital_labels)]
    attribution_vital = vb.primary_cause.value_counts(normalize=True).round(3).to_dict() if len(vb) else {}
    shortfall_share = {}
    if q.realtime and len(b):
        lost = {n: float((b[f"shap_{n}"].clip(lower=0) * b.sl_den).sum()) for n in names.values()}
        tot = sum(lost.values()) or 1
        shortfall_share = {k: round(v / tot, 3) for k, v in sorted(lost.items(), key=lambda x: -x[1])}
    for t in tests:
        t["primary_share"] = float(attribution.get(t["hypothesis"], 0.0))
        t["primary_share_vital"] = float(attribution_vital.get(t["hypothesis"], 0.0))
        t["verdict"] = _verdict(max(t["primary_share"], t["primary_share_vital"]), t["p_value"], t["effect_ok"])
    by_cause_label = (b.groupby(["label", "primary_cause"]).size().unstack(fill_value=0)
                      .reindex(par.label).fillna(0).astype(int))
    pareto_causes = [{"label": k, **{c: int(v) for c, v in row.items()}} for k, row in by_cause_label.iterrows()]

    # change point on the vital-few intervals (structural changes hide in all-interval noise)
    vf = e[e.label.isin(vital_labels)]
    cp = change_point(vf.groupby("date").breach.mean()) if len(vf) else None
    cp_staff = change_point(vf.groupby("date").staff_ratio.mean()) if len(vf) else None

    # 5. staffing gap + what-if (Erlang C at required staffing)
    focus = b[b.label.isin(vital_labels)]
    if cp and cp["significant"]:
        focus = focus[focus.date >= cp["date"]]
    gap = focus.groupby("label").agg(breach_days=("date", "nunique"), forecast=("forecast_volume", "mean"), actual=("offered", "mean"),
                                     required=("required_agents", "mean"), scheduled=("scheduled_agents", "mean"),
                                     staffed=("staffed_agents", "mean"), sl=("sl_num", "sum"), den=("sl_den", "sum"),
                                     abandoned=("abandoned", "sum"), short=("short_abandoned", "sum"),
                                     staffing_cause=("primary_cause", lambda s: float((s == "Staffing shortfall").mean()))).reset_index()
    gap["sl"] = gap.sl / gap.den
    gap["gap_agents"] = (gap.required - gap.staffed).clip(lower=0)
    gap["heads_to_add"] = np.ceil(gap.gap_agents / (1 - config.PLANNED_SHRINKAGE) - 1e-9).clip(lower=0)
    gap["scheduled_vs_needed"] = gap.scheduled / (gap.required / (1 - config.PLANNED_SHRINKAGE))
    gap = gap.sort_values("label")

    if q.realtime:
        uplift = np.where(e.breach & e.label.isin(vital_labels) & (e.primary_cause == "Staffing shortfall"),
                          np.clip(fix_staff - base_m, 0, 1), 0)
        projected_num = e.sl_num + uplift * e.sl_den
        fsel = e.breach & e.label.isin(vital_labels)
        whatif = {"actual_sl": round(float(e.sl_num.sum() / e.sl_den.sum()), 4),
                  "projected_sl": round(float(min(projected_num.sum(), e.sl_den.sum()) / e.sl_den.sum()), 4),
                  "focus_actual_sl": round(float(e[fsel].sl_num.sum() / max(e[fsel].sl_den.sum(), 1)), 4),
                  "focus_projected_sl": round(float(np.average(np.clip(fix_staff[fsel.values], 0, 1), weights=e[fsel].sl_den)), 4) if fsel.any() else None,
                  "method": "Erlang C with actual volume and handle time; staffing raised to the WFM requirement where staffing was the primary cause in the vital-few intervals"}
    else:
        whatif = None
    staff_lead = attribution_vital.get("Staffing shortfall", 0)

    abandoned_in_breach = int((b.abandoned - b.short_abandoned).sum())
    top = sorted(tests, key=lambda t: -t["primary_share_vital"])
    lead = top[0] if top else None
    summary = []
    misses = int(e.miss.sum())
    summary.append(f"{misses} of {len(e)} intervals ({misses / len(e):.0%}) finished under the {q.sl_target:.0%} target; "
                   f"{total_b} ({total_b / len(e):.0%}) were under it by more than random variation at their volume and are treated as breaches.")
    if hotspots:
        hs = par[par.hotspot]
        summary.append(f"Breaches cluster in {len(hotspots)} recurring hotspot intervals ({', '.join(sorted(hotspots))}): "
                       f"{hs.breaches.sum() / max(total_b, 1):.0%} of all breaches, with a breach rate of {hs.breaches.sum() / hs.intervals.sum():.0%} "
                       f"against {base_rate:.0%} for the queue.")
    else:
        summary.append(f"No recurring hotspot: no interval breaches significantly more often than the queue average ({base_rate:.0%}); "
                       f"breaches are scattered through the day.")
    if cp and cp["significant"]:
        summary.append(f"The daily breach rate changed on {cp['date']}: {cp['before']:.0%} of intervals before, {cp['after']:.0%} after.")
    if lead and attribution_vital:
        summary.append(f"Shapley attribution (Erlang C): in the {'hotspot' if hotspots else 'breach'} intervals, {lead['hypothesis'].lower()} is the primary cause of "
                       f"{lead['primary_share_vital']:.0%} of breaches" + (f" (across all intervals: {lead['primary_share']:.0%})." if hotspots else "."))
    if cp_staff and cp_staff["significant"]:
        summary.append(f"Staffed-to-required ratio in those intervals fell from {cp_staff['before']:.2f} to {cp_staff['after']:.2f} on {cp_staff['date']}.")
    if len(gap) and hotspots:
        summary.append(f"In those intervals staffing averaged {gap.staffed.mean():.1f} agents against {gap.required.mean():.1f} required; "
                       f"closing the gap needs about {int(gap.heads_to_add.max())} more rostered heads at the worst interval.")
    if whatif and hotspots:
        summary.append(f"Erlang C estimate: staffing the hotspot intervals to requirement lifts the queue from {whatif['actual_sl']:.1%} to "
                       f"{whatif['projected_sl']:.1%} service level.")
    summary.append(f"{abandoned_in_breach:,} callers abandoned during breach intervals.")

    return {
        "queue_id": queue_id, "queue_code": q.code, "queue_name": q.name, "channel": q.channel, "target": q.sl_target,
        "range": {"start": str(e.date.min()), "end": str(e.date.max())}, "min_offered": min_offered,
        "totals": {"intervals": int(len(e)), "misses": int(e.miss.sum()), "breaches": total_b, "breach_rate": round(total_b / len(e), 4),
                   "abandoned_in_breach": abandoned_in_breach},
        "pareto": par.round(4).to_dict("records"), "vital_few": vital_labels, "hotspots": hotspots, "base_breach_rate": round(base_rate, 4),
        "by_weekday": seg_wd.round(4).to_dict("records"), "by_shift": seg_sh.round(4).to_dict("records"),
        "weekly": weekly.round(4).to_dict("records"), "change_point": cp, "change_point_staffing": cp_staff,
        "hypotheses": tests, "attribution": attribution, "attribution_vital": attribution_vital, "shortfall_share": shortfall_share,
        "attribution_method": "Shapley decomposition of each breach interval's service-level gap over an Erlang C model (staffing, volume and handle time reset to plan in all 8 combinations)",
        "pareto_causes": pareto_causes,
        "daily_vital": vf.groupby("date").agg(breach_rate=("breach", "mean"), staff_ratio=("staff_ratio", "mean"),
                                               sl_num=("sl_num", "sum"), sl_den=("sl_den", "sum")).reset_index().round(4).to_dict("records") if len(vf) else [],
        "staffing_gap": gap.round(3).to_dict("records"),
        "whatif": whatif, "summary": summary,
    }
