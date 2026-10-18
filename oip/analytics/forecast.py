"""Daily volume forecasting with a chronological split, plus a forecast-to-staffing plan.

Features (as specified by the team): lag values, rolling means, day of week,
month, holiday indicator, staffing ratio and prior-day handle time.
Models are judged against a moving-average baseline on a hold-out period that
comes strictly after the training period (a random split would leak future
information through the lag features).

The best model per queue then produces a 14-day forecast, which is spread over
intervals with the recent intraday profile and converted to required agents
with Erlang C, giving a staffing plan to compare with the current roster.
"""
from __future__ import annotations

import warnings
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from oip import config, db
from oip.analytics.erlang import required_agents
from oip.reference import HOLIDAYS, QUEUE_BY_ID, QUEUES

warnings.filterwarnings("ignore", category=UserWarning)

TEST_START = pd.Timestamp("2026-05-11")
HORIZON = 14
FEATURES = ["lag_1", "lag_7", "lag_14", "roll_mean_7", "roll_mean_28", "roll_std_7", "dow", "month", "is_holiday",
            "pre_holiday", "staffing_ratio_lag1", "aht_lag1", "day_of_month", "trend"]


def daily_frame() -> pd.DataFrame:
    d = db.read_sql("""SELECT queue_id, d.date, SUM(offered) offered, SUM(handle_sec) handle_sec, SUM(handled) handled,
                              SUM(staffed_agents) staffed, SUM(required_agents) required
                       FROM rpt_interval_cube c JOIN dim_date d USING(date_key) GROUP BY queue_id, d.date ORDER BY queue_id, d.date""")
    d["date"] = pd.to_datetime(d.date)
    d["aht"] = d.handle_sec / d.handled.replace(0, np.nan)
    d["staffing_ratio"] = d.staffed / d.required.replace(0, np.nan)
    return d


def make_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()
    y = g.offered
    g["lag_1"], g["lag_7"], g["lag_14"] = y.shift(1), y.shift(7), y.shift(14)
    g["roll_mean_7"] = y.shift(1).rolling(7).mean()
    g["roll_mean_28"] = y.shift(1).rolling(28, min_periods=14).mean()
    g["roll_std_7"] = y.shift(1).rolling(7).std()
    g["dow"] = g.date.dt.dayofweek
    g["month"] = g.date.dt.month
    g["day_of_month"] = g.date.dt.day
    hol = {pd.Timestamp(k) for k in HOLIDAYS}
    g["is_holiday"] = g.date.isin(hol).astype(int)
    g["pre_holiday"] = (g.date + pd.Timedelta(days=1)).isin(hol).astype(int)
    g["staffing_ratio_lag1"] = g.staffing_ratio.shift(1)
    g["aht_lag1"] = g.aht.shift(1)
    g["trend"] = (g.date - g.date.min()).dt.days
    return g


def _metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    err = p - y
    return {"mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2))),
            "mape": float(np.mean(np.abs(err) / np.maximum(y, 1)) * 100), "bias": float(np.mean(err))}


def _models():
    dow_dummies = None
    return {
        "Linear regression": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "Random forest": RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=7, n_jobs=-1),
        "Gradient boosting": HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                                           l2_regularization=0.5, random_state=7),
    }


def _design(g: pd.DataFrame) -> pd.DataFrame:
    X = g[FEATURES].copy()
    for k in range(7):
        X[f"dow_{k}"] = (g.dow == k).astype(int)
    return X


def run_forecast(verbose=True) -> dict:
    d = daily_frame()
    results, preds, importances, plans, forecasts = [], [], {}, [], []
    for q in QUEUES:
        g = make_features(d[d.queue_id == q.queue_id]).dropna(subset=["lag_14", "roll_mean_7", "aht_lag1", "staffing_ratio_lag1"])
        train, test = g[g.date < TEST_START], g[g.date >= TEST_START]
        Xtr, Xte = _design(train), _design(test)
        base = test.roll_mean_7.values                       # moving-average baseline
        snaive = test.lag_7.values                           # seasonal naive (same weekday last week)
        row = {"queue_id": q.queue_id, "queue_code": q.code, "train_days": int(len(train)), "test_days": int(len(test)),
               "models": {"Moving average (7-day)": _metrics(test.offered, base),
                          "Seasonal naive (t-7)": _metrics(test.offered, snaive)}}
        p_df = pd.DataFrame({"queue_id": q.queue_id, "date": test.date.dt.strftime("%Y-%m-%d"), "actual": test.offered.values,
                             "Moving average (7-day)": base.round(1), "Seasonal naive (t-7)": snaive})
        fitted = {}
        for name, m in _models().items():
            m.fit(Xtr, train.offered)
            p = m.predict(Xte)
            row["models"][name] = _metrics(test.offered, p)
            p_df[name] = np.round(p, 1)
            fitted[name] = m
        best = min((k for k in row["models"]), key=lambda k: row["models"][k]["mape"])
        row["best_model"] = best
        row["baseline_mape"] = row["models"]["Moving average (7-day)"]["mape"]
        row["improvement_vs_baseline"] = round(1 - row["models"][best]["mape"] / row["baseline_mape"], 4)
        results.append(row)
        preds.append(p_df)
        rf = fitted["Random forest"]
        importances[q.code] = dict(sorted(zip(Xtr.columns, rf.feature_importances_.round(4)), key=lambda x: -x[1])[:10])

        # ---- 14-day forecast with the best ML model (refit on all data), recursive
        model_name = best if best in fitted else "Gradient boosting"
        m = _models()[model_name]
        Xall = _design(g)
        m.fit(Xall, g.offered)
        hist = d[d.queue_id == q.queue_id].sort_values("date").copy()
        last = hist.date.max()
        sr = float(hist.staffing_ratio.tail(28).mean())
        aht_recent = float(hist.aht.tail(14).mean())
        for h in range(1, HORIZON + 1):
            day = last + pd.Timedelta(days=h)
            ext = pd.concat([hist, pd.DataFrame([{"queue_id": q.queue_id, "date": day, "offered": np.nan, "aht": aht_recent,
                                                   "staffing_ratio": sr}])], ignore_index=True)
            f = make_features(ext).iloc[[-1]]
            f["staffing_ratio_lag1"] = sr
            f["aht_lag1"] = aht_recent
            yhat = float(m.predict(_design(f))[0])
            hist = pd.concat([hist, pd.DataFrame([{"queue_id": q.queue_id, "date": day, "offered": yhat, "aht": aht_recent,
                                                    "staffing_ratio": sr}])], ignore_index=True)
            forecasts.append({"queue_id": q.queue_id, "date": day.strftime("%Y-%m-%d"), "forecast": round(yhat, 1), "model": model_name})

    pred = pd.concat(preds, ignore_index=True)
    fc = pd.DataFrame(forecasts)
    plan = staffing_plan(fc)
    overall = {}
    for name in results[0]["models"]:
        ms = [r["models"][name]["mape"] for r in results]
        overall[name] = round(float(np.mean(ms)), 2)
    out = {"test_start": TEST_START.strftime("%Y-%m-%d"), "features": FEATURES, "results": results, "overall_mape": overall,
           "predictions": pred.to_dict("records"), "importance": importances, "forecast": fc.to_dict("records"),
           "staffing_plan": plan,
           "notes": ["Chronological split: train before 11 May 2026, test 11-31 May (21 days). No shuffling.",
                     "Baseline: 7-day moving average of the previous week. A model is only useful if it beats this.",
                     "Kestrel's 15-18 May sale is not a feature (no promotions calendar), so every model under-calls it; adding a promotions flag is the next improvement."]}
    if verbose:
        best_names = pd.Series([r["best_model"] for r in results]).value_counts().to_dict()
        print(f"  [forecast] mean MAPE {overall}; best models {best_names}", flush=True)
    return out


def staffing_plan(fc: pd.DataFrame) -> dict:
    """Spread daily forecasts over intervals, convert to required agents, compare with the recent roster."""
    cube = db.read_sql("""SELECT c.queue_id, d.date, d.weekday_num, c.interval_idx, c.offered, c.scheduled_agents, c.handle_sec, c.handled
                          FROM rpt_interval_cube c JOIN dim_date d USING(date_key) WHERE d.date >= '2026-04-20'""")
    cube["date"] = pd.to_datetime(cube.date)
    rows = []
    for q in QUEUES:
        cq = cube[cube.queue_id == q.queue_id]
        prof = cq.groupby(["weekday_num", "interval_idx"]).offered.sum()
        prof = prof / prof.groupby(level=0).transform("sum")
        aht = float(cq.handle_sec.sum() / max(cq.handled.sum(), 1))
        roster = cq[cq.date >= cq.date.max() - pd.Timedelta(days=13)].groupby(["weekday_num", "interval_idx"]).scheduled_agents.mean()
        for r in fc[fc.queue_id == q.queue_id].itertuples():
            day = pd.Timestamp(r.date)
            wd = day.dayofweek + 1
            if wd not in prof.index.get_level_values(0):
                continue
            p = prof.loc[wd]
            vol = r.forecast * p
            if q.realtime:
                req = required_agents(vol.values, aht, q.sl_threshold_sec, q.sl_target)
                req = np.ceil(req / q.concurrency)
            else:
                handling = [(i >= q.open_hour * 2) and (i < q.close_hour * 2) for i in p.index]
                per = r.forecast * aht / (sum(handling) * 1800 * config.OCCUPANCY_TARGET)
                req = np.where(handling, np.ceil(per), 0)
            heads = np.ceil(req / (1 - config.PLANNED_SHRINKAGE))
            cur = roster.loc[wd].reindex(p.index).fillna(0).values if wd in roster.index.get_level_values(0) else np.zeros(len(p))
            for i, v, rq, hd, c in zip(p.index, vol.values, req, heads, cur):
                if rq <= 0 and v < 0.5:
                    continue
                rows.append({"queue_id": q.queue_id, "date": r.date, "interval_idx": int(i), "forecast": round(float(v), 2),
                             "required": int(rq), "heads_needed": int(hd), "current_roster": round(float(c), 1),
                             "gap": round(float(hd - c), 1)})
    df = pd.DataFrame(rows)
    summary = (df.groupby("queue_id").agg(days=("date", "nunique"), forecast=("forecast", "sum"), heads_interval_sum=("heads_needed", "sum"),
                                          roster_interval_sum=("current_roster", "sum"), short_intervals=("gap", lambda s: int((s >= 1).sum())))
               .reset_index())
    summary["coverage"] = (summary.roster_interval_sum / summary.heads_interval_sum).round(3)
    worst = (df[df.gap >= 1].groupby(["queue_id", "interval_idx"]).agg(days=("date", "nunique"), avg_gap=("gap", "mean"))
             .reset_index().sort_values(["queue_id", "avg_gap"], ascending=[True, False]))
    return {"intervals": df.to_dict("records"), "summary": summary.round(2).to_dict("records"),
            "worst_gaps": worst.round(2).to_dict("records")}
