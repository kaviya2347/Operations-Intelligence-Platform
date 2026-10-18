"""Synthetic source systems for the Operations Intelligence Platform.

Production data is confidential and contains customer PII, so the platform ships
with a simulator that reproduces the *shape* of the real extracts:

  dialler (voice ACD)    chat platform        email & back-office case tools
  CRM cases + status     CSAT surveys         QA audits
  WFM plan + staffed     agent sessions       HR roster
  source daily reports (for reconciliation)

Queue behaviour is driven by Erlang C: when staffing falls below what the volume
needs, waits grow, callers abandon and service level drops. Planted scenarios
(reference.SCENARIOS) give root-cause analysis, anomaly detection and
forecasting something real to find. Typical data-quality defects are injected on
the way out (label drift, duplicates, missing values, mixed timestamp formats,
unclosed sessions) so the cleaning pipeline has real work to do.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from oip import config
from oip.analytics.erlang import erlang_c, required_agents
from oip.reference import (CLIENTS, DOW_FACTOR, EMAIL_DOMAINS, FIRST_NAMES, HOLIDAYS, HOURLY_SHAPE, HOURLY_SHAPE_ASYNC,
                           LAST_NAMES, QUEUES, REASONS, REPEAT_RATE, RESOLUTION_LABELS, SCENARIOS, SHIFTS, SITES, Queue)

IV = 1800  # interval seconds
N_IV = 48
TENURE_MULT = {"0-3m": 1.22, "3-6m": 1.10, "6-12m": 1.00, "12m+": 0.93}


def _log(msg, verbose):
    if verbose:
        print(f"  [generate] {msg}", flush=True)


def _iv_label(i):
    return f"{i // 2:02d}:{'30' if i % 2 else '00'}"


# ---------------------------------------------------------------------------
# 1. WFM plan, staffing and true demand
# ---------------------------------------------------------------------------
def build_plan(rng: np.random.Generator, dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    n_days = len(dates)
    dows = dates.dayofweek.values
    for q in QUEUES:
        shape = np.repeat(np.array(HOURLY_SHAPE if q.realtime else HOURLY_SHAPE_ASYNC), 2) / 2.0
        arrival = np.zeros(N_IV, bool)
        handling = np.zeros(N_IV, bool)
        handling[q.open_hour * 2: q.close_hour * 2] = True
        arrival[:] = not q.realtime
        arrival |= handling
        share = np.where(arrival, shape, 0)
        share = share / share.sum()

        # daily expected volume
        day_mult = np.array([DOW_FACTOR[d] for d in dows])
        if q.client_id == "C03":                                   # e-commerce client is growing
            day_mult *= 1 + 0.0012 * np.arange(n_days)
        hol = np.array([HOLIDAYS.get(d.date(), (None, 1.0))[1] for d in dates])
        day_mult *= hol
        event_true = np.ones(n_days)
        event_fc = np.ones(n_days)
        bc = SCENARIOS["billing_cycle"]
        if q.queue_id == bc["queue"]:
            m = np.isin(dates.day, bc["days"])
            event_true[m] *= bc["mult"]
            event_fc[m] *= bc["mult"] * 0.97
        ks = SCENARIOS["kestrel_sale"]
        for key, qid in (("orders", "Q06"), ("returns", "Q08")):
            if q.queue_id == qid:
                s, e, true_m, fc_m = ks[key]
                m = (dates.date >= s) & (dates.date <= e)
                event_true[m] *= true_m
                event_fc[m] *= fc_m
        expected_day = q.base_daily_volume * day_mult * event_true
        actual_day = expected_day * np.exp(rng.normal(0, 0.05, n_days))
        fc_day = q.base_daily_volume * day_mult * event_fc * np.exp(rng.normal(0, 0.045, n_days))

        exp_iv = actual_day[:, None] * share[None, :]
        fc_iv = fc_day[:, None] * share[None, :] * np.exp(rng.normal(0, 0.05, (n_days, N_IV)))
        fc_iv = np.where(arrival[None, :], fc_iv, 0)

        # AHT reality vs plan
        aht_mult = 1 + rng.normal(0, 0.025, n_days)
        cl = SCENARIOS["cards_latency"]
        if q.queue_id == cl["queue"]:
            m = (dates.date >= cl["start"]) & (dates.date <= cl["end"])
            aht_mult[m] *= cl["aht_mult"]
        fc_aht = np.full(n_days, q.base_aht_sec)

        # required agents (WFM)
        if q.realtime:
            req_servers = required_agents(fc_iv.ravel(), np.repeat(fc_aht, N_IV), q.sl_threshold_sec, q.sl_target).reshape(n_days, N_IV)
            req = np.ceil(req_servers / q.concurrency)
            req = np.where(handling[None, :], np.maximum(req, 1), 0)
        else:
            work = fc_day * q.base_aht_sec
            per_iv = work / (handling.sum() * IV * config.OCCUPANCY_TARGET)
            req = np.where(handling[None, :], np.maximum(np.ceil(per_iv[:, None]), 1), 0)

        # scheduled heads (planner variance + planted roster gap)
        sched_factor = rng.uniform(1.06, 1.16, n_days)[:, None] * np.ones((1, N_IV))
        sc = SCENARIOS["billing_roster_gap"]
        if q.queue_id == sc["queue"]:
            weekday_after = (dates.date >= sc["start"]) & (dows < 5)
            sat_after = (dates.date >= sc["start"]) & (dows == 5)
            for lbl, f in sc["intervals"].items():
                i = int(lbl[:2]) * 2 + (1 if lbl[3:] == "30" else 0)
                sched_factor[weekday_after, i] *= f
                sched_factor[sat_after, i] *= min(1.0, f + 0.15)
        sched = np.where(req > 0, np.maximum(np.round(req / (1 - config.PLANNED_SHRINKAGE) * sched_factor), 1), 0)

        # actual shrinkage and staffed agents
        shrink = 0.30 + rng.normal(0, 0.028, n_days)
        shrink += np.where(dows == 0, 0.025, 0)
        after_hol = np.isin((dates - pd.Timedelta(days=1)).date, list(HOLIDAYS))
        shrink += np.where(after_hol, 0.04, 0)
        shrink += np.where(rng.random(n_days) < 0.04, 0.09, 0)
        shrink = np.clip(shrink, 0.18, 0.55)
        staffed_f = sched * (1 - shrink[:, None]) * np.exp(rng.normal(0, 0.03, (n_days, N_IV)))
        staffed = np.floor(staffed_f) + (rng.random(staffed_f.shape) < (staffed_f - np.floor(staffed_f)))
        staffed = np.where(handling[None, :], np.maximum(staffed, 1), 0)

        for di in range(n_days):
            for i in range(N_IV):
                if not arrival[i] and not handling[i]:
                    continue
                rows.append((dates[di].date(), i, q.queue_id, float(exp_iv[di, i]), float(fc_iv[di, i]), float(fc_aht[di]),
                             int(req[di, i]), int(sched[di, i]), int(staffed[di, i]), float(aht_mult[di]), float(shrink[di]),
                             bool(handling[i])))
    plan = pd.DataFrame(rows, columns=["date", "iv", "queue_id", "lam", "fc_volume", "fc_aht", "required", "scheduled",
                                       "staffed", "aht_mult", "shrinkage", "handling"])
    return plan


# ---------------------------------------------------------------------------
# 2. Agents, team leaders, rosters
# ---------------------------------------------------------------------------
def build_agents(rng, plan: pd.DataFrame, dates: pd.DatetimeIndex):
    agents, tls = [], []
    aid = 0
    tlid = 0
    mid = date(2026, 4, 15)
    for q in QUEUES:
        p = plan[(plan.queue_id == q.queue_id) & plan.handling]
        day_hours = p.groupby("date").scheduled.sum() * 0.5
        heads = int(np.ceil(day_hours.max() / 8.0 * 7 / 6 * 1.08))
        cover = {}
        for s, (h0, h1) in SHIFTS.items():
            ivs = [i for i in range(N_IV) if h0 * 2 <= i < h1 * 2 and q.open_hour * 2 <= i < q.close_hour * 2]
            cover[s] = ivs
        ncov = np.zeros(N_IV)
        for s in cover:
            for i in cover[s]:
                ncov[i] += 1
        sched_by_iv = p.groupby("iv").scheduled.mean()
        weight = {s: sum(sched_by_iv.get(i, 0) / max(ncov[i], 1) for i in cover[s]) for s in cover}
        tot = sum(weight.values()) or 1
        for s in SHIFTS:
            n_s = int(round(heads * weight[s] / tot))
            if n_s == 0 or not cover[s]:
                continue
            n_tl = max(1, int(np.ceil(n_s / 13)))
            tl_ids = []
            for _ in range(n_tl):
                tlid += 1
                fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                tls.append({"team_leader_id": f"TL{tlid:03d}", "team_leader_name": f"{fn} {ln}", "queue_code": q.code, "shift": s})
                tl_ids.append(f"TL{tlid:03d}")
            for k in range(n_s):
                aid += 1
                r = rng.random()
                if r < 0.08:
                    doj = pd.Timestamp(dates[0]) + pd.Timedelta(days=int(rng.integers(5, 70)))   # joined during period
                else:
                    months = rng.choice([1.5, 4.5, 9, 18, 30], p=[0.12, 0.17, 0.25, 0.26, 0.20])
                    doj = pd.Timestamp(mid) - pd.Timedelta(days=int(months * 30 + rng.integers(-20, 20)))
                ten_days = (pd.Timestamp(mid) - doj).days
                band = "0-3m" if ten_days < 90 else "3-6m" if ten_days < 180 else "6-12m" if ten_days < 365 else "12m+"
                quality = float(np.clip(rng.normal(0, 1) + (0.4 if band == "12m+" else -0.5 if band == "0-3m" else 0), -2.5, 2.5))
                speed = TENURE_MULT[band] * float(np.exp(rng.normal(0, 0.08)))
                fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                agents.append({
                    "agent_id": f"A{aid:04d}", "agent_login": f"{q.code.split('-')[0].lower()}{aid:04d}",
                    "full_name": f"{fn} {ln}", "site": SITES[0] if rng.random() < 0.64 else SITES[1],
                    "team_leader_id": tl_ids[k % n_tl], "queue_code": q.code, "queue_id": q.queue_id, "shift": s,
                    "date_of_joining": doj.date(), "tenure_band_mid": band, "_quality": quality, "_speed": speed,
                    "_off_dow": int(rng.integers(0, 7)),
                })
    agents = pd.DataFrame(agents)
    tls = pd.DataFrame(tls)
    # presence matrix (agent x day): weekly off, leave, not yet joined
    n_days = len(dates)
    present = np.ones((len(agents), n_days), bool)
    dows = dates.dayofweek.values
    for j, a in agents.iterrows():
        present[j] &= dows != a["_off_dow"]
        present[j] &= rng.random(n_days) > 0.035
        present[j] &= dates.date >= a["date_of_joining"]
    return agents, tls, present


# ---------------------------------------------------------------------------
# 3. Interactions
# ---------------------------------------------------------------------------
def _business_add(arrival: pd.Series, business_sec: np.ndarray, open_h: int, close_h: int) -> pd.Series:
    """Add business seconds (inside handling hours, 7-day operation) to calendar timestamps."""
    day = arrival.dt.normalize()
    sec = (arrival - day).dt.total_seconds().values
    o, c = open_h * 3600, close_h * 3600
    cap = c - o
    start_day = day + pd.to_timedelta(np.where(sec >= c, 1, 0), unit="D")
    start_sec = np.where(sec < o, o, np.where(sec >= c, o, sec))
    avail = c - start_sec
    rem = business_sec
    same = rem <= avail
    rem2 = rem - avail
    extra_days = np.floor(np.maximum(rem2, 0) / cap) + 1
    final_sec = np.where(same, start_sec + rem, o + np.mod(np.maximum(rem2, 0), cap))
    final_day = start_day + pd.to_timedelta(np.where(same, 0, extra_days), unit="D")
    return final_day + pd.to_timedelta(final_sec, unit="s")


def simulate_interactions(rng, plan, agents, present, dates):
    base = pd.Timestamp(dates[0])
    day_index = {d.date(): k for k, d in enumerate(dates)}
    out = []
    for q in QUEUES:
        p = plan[plan.queue_id == q.queue_id].reset_index(drop=True)
        n = rng.poisson(p.lam.values)
        rep = np.repeat(np.arange(len(p)), n)
        if rep.size == 0:
            continue
        pp = p.iloc[rep].reset_index(drop=True)
        di = pp.date.map(day_index).values
        start = base + pd.to_timedelta(di, unit="D") + pd.to_timedelta(pp.iv.values * IV + rng.uniform(0, IV, rep.size), unit="s")
        aht_q = q.base_aht_sec * pp.aht_mult.values
        df = pd.DataFrame({"queue_id": q.queue_id, "start_ts": start, "date": pp.date.values, "iv": pp.iv.values, "day_idx": di})

        # agents available for each (day, interval)
        qa = agents[agents.queue_id == q.queue_id]
        qa_idx = qa.index.values
        shift_ivs = {s: set(range(int(h0 * 2), int(h1 * 2))) for s, (h0, h1) in SHIFTS.items()}

        if q.realtime:
            servers = (pp.staffed.values * q.concurrency).astype(float)
            n_iv = pd.Series(n[n > 0], index=np.nonzero(n)[0])
            n_in = n_iv.reindex(rep).values
            load = n_in * aht_q / IV
            servers = np.where(servers < 1, 1, servers)
            c = erlang_c(servers, load)
            # Erlang C overstates waits when callers abandon (they shorten the queue); a 0.45
            # factor approximates Erlang A for patience in the 2-4 minute range.
            mean_wait = 0.45 * np.where(servers > load, aht_q / np.maximum(servers - load, 1e-6),
                                        150 + 300 * (load - servers + 1) / np.maximum(servers, 1))
            waits = np.where(rng.random(rep.size) < c, rng.exponential(mean_wait), 0.0)
            patience = rng.exponential(q.patience_sec, rep.size)
            abandoned = waits > patience
            wait = np.where(abandoned, patience, waits)
            df["wait_sec"] = np.round(wait, 1)
            df["abandoned"] = abandoned
        else:
            # backlog drives first response time (business seconds)
            h = p[p.handling].groupby("date").agg(req=("required", "sum"), stf=("staffed", "sum"))
            backlog = np.clip((h.req / h.stf.clip(lower=1)) ** 2, 0.5, 8.0)
            day_vol = pd.Series(n, index=p.index).groupby(p.date).sum()
            vol_ratio = (day_vol / p.groupby("date").fc_volume.sum().clip(lower=1)).clip(0.6, 2.5) ** 1.5
            mean_b = (70 * 60 if q.channel == "Email" else 3.2 * 3600) * (backlog * vol_ratio.reindex(backlog.index))
            mb = pd.Series(df.date.map(mean_b).values).fillna(4000).values
            bwait = rng.exponential(mb)
            df["wait_sec"] = np.round(bwait, 0)
            df["abandoned"] = False
            df["first_response_ts"] = _business_add(df.start_ts, bwait, q.open_hour, q.close_hour)

        # assign agents to handled contacts
        handled_mask = ~df.abandoned.values
        agent_col = np.full(len(df), -1)
        resp_iv = df.iv.values.copy()
        resp_day = df.day_idx.values.copy()
        if not q.realtime:
            fr = df.first_response_ts
            resp_day = ((fr.dt.normalize() - base).dt.days.values).clip(0, len(dates) - 1)
            resp_iv = ((fr - fr.dt.normalize()).dt.total_seconds().values // IV).astype(int)
        key = resp_day * 100 + resp_iv
        order = np.argsort(key, kind="stable")
        ks = key[order]
        bounds = np.flatnonzero(np.diff(ks)) + 1
        for grp in np.split(order, bounds):
            g = grp[handled_mask[grp]]
            if g.size == 0:
                continue
            d, i = resp_day[g[0]], resp_iv[g[0]]
            on = [j for j in qa_idx if present[j, d] and i in shift_ivs[agents.at[j, "shift"]]]
            if not on:
                on = [j for j in qa_idx if present[j, d]] or list(qa_idx)
            agent_col[g] = rng.choice(on, size=g.size)
        df["agent_idx"] = agent_col

        # handle time
        speed = np.where(agent_col >= 0, agents._speed.values[np.maximum(agent_col, 0)], 1.0)
        sigma = 0.48
        handle = aht_q * speed * np.exp(rng.normal(-sigma ** 2 / 2, sigma, len(df)))
        handle = np.clip(handle, 25, None)
        if q.channel == "Voice":
            acw = handle * rng.uniform(0.10, 0.20, len(df))
            hold = np.where(rng.random(len(df)) < 0.45, 0.0, handle * rng.uniform(0.04, 0.25, len(df)))
            talk = handle - acw - hold
        elif q.channel == "Chat":
            acw = rng.uniform(20, 70, len(df))
            hold = np.zeros(len(df))
            talk = handle - acw
        else:
            acw = np.zeros(len(df))
            hold = np.zeros(len(df))
            talk = handle
        df["talk_sec"] = np.where(handled_mask, np.round(talk), 0)
        df["hold_sec"] = np.where(handled_mask, np.round(hold), 0)
        df["acw_sec"] = np.where(handled_mask, np.round(acw), 0)
        df["transferred"] = handled_mask & (rng.random(len(df)) < (0.10 if q.code == "NWT-TECH" else 0.05 if q.channel == "Voice" else 0.02))

        # resolution at handle time
        qual = np.where(agent_col >= 0, agents._quality.values[np.maximum(agent_col, 0)], 0.0)
        p_res = np.clip(0.80 + 0.045 * qual - (0.06 if q.code in ("NWT-TECH", "HAL-CLM") else 0), 0.5, 0.95)
        u = rng.random(len(df))
        rem = 1 - p_res
        status = np.where(u < p_res, "Resolved",
                          np.where(u < p_res + rem * 0.40, "Escalated",
                                   np.where(u < p_res + rem * 0.70, "Callback scheduled", "Pending customer")))
        df["resolution"] = np.where(handled_mask, status, None)
        df["reason"] = np.where(handled_mask, rng.choice(REASONS[q.queue_id], len(df), p=[0.34, 0.24, 0.18, 0.14, 0.10]), None)
        df["channel"] = q.channel
        out.append(df)
        _ = start
    inter = pd.concat(out, ignore_index=True).sort_values("start_ts").reset_index(drop=True)
    return inter


# ---------------------------------------------------------------------------
# 4. Customers and repeat contacts
# ---------------------------------------------------------------------------
def assign_customers(rng, inter: pd.DataFrame, agents: pd.DataFrame):
    qclient = {q.queue_id: q.client_id for q in QUEUES}
    inter["client_id"] = inter.queue_id.map(qclient)
    cust = np.full(len(inter), -1, dtype=np.int64)
    counters = {c["client_id"]: 0 for c in CLIENTS}
    offsets = {c["client_id"]: k * 10_000_000 for k, c in enumerate(CLIENTS)}
    tenure = np.where(inter.agent_idx.values >= 0, agents.tenure_band_mid.values[np.maximum(inter.agent_idx.values, 0)], "")
    weights_all = 1.0 + 3.0 * (inter.resolution.values != "Resolved") + 1.0 * (tenure == "0-3m")
    for qid, g in inter.groupby("queue_id"):
        cid = qclient[qid]
        idx = g.index.values
        days = g.day_idx.values
        for d in np.unique(days):
            sel = idx[days == d]
            prior = idx[(days >= d - 7) & (days < d)]
            if prior.size:
                is_rep = rng.random(sel.size) < REPEAT_RATE[qid]
            else:
                is_rep = np.zeros(sel.size, bool)
            nrep = int(is_rep.sum())
            if nrep:
                w = weights_all[prior]
                parents = rng.choice(prior, size=nrep, p=w / w.sum())
                cust[sel[is_rep]] = cust[parents]
            nnew = sel.size - nrep
            ids = offsets[cid] + counters[cid] + np.arange(nnew)
            counters[cid] += nnew
            cust[sel[~is_rep]] = ids
    inter["customer_num"] = cust
    return inter


def build_customers(rng, inter):
    nums = np.unique(inter.customer_num.values)
    n = nums.size
    fn = rng.choice(FIRST_NAMES, n)
    ln = rng.choice(LAST_NAMES, n)
    phone = (rng.choice([9, 8, 7, 6], n) * 10**9 + rng.integers(0, 10**9, n)).astype(np.int64).astype(str)
    dom = rng.choice(EMAIL_DOMAINS, n)
    suffix = rng.integers(1, 999, n).astype(str)
    email = pd.Series(fn).str.lower() + "." + pd.Series(ln).str.lower() + suffix + "@" + dom
    client = np.array([CLIENTS[int(x // 10_000_000)]["client_code"] for x in nums])
    cust = pd.DataFrame({"customer_num": nums,
                         "customer_id": [f"CUST-{c}-{int(x % 10_000_000):07d}" for c, x in zip(client, nums)],
                         "client_code": client, "full_name": pd.Series(fn) + " " + pd.Series(ln), "phone": phone,
                         "email": email.values,
                         "city": rng.choice(["Chennai", "Coimbatore", "Madurai", "Bengaluru", "Hyderabad", "Mumbai", "Pune", "Delhi"], n),
                         })
    return cust


# ---------------------------------------------------------------------------
# 5. Output assembly with data-quality defects
# ---------------------------------------------------------------------------
def _fmt(ts: pd.Series, rng, alt_share=0.0):
    s = ts.dt.strftime("%Y-%m-%d %H:%M:%S")
    if alt_share:
        m = rng.random(len(ts)) < alt_share
        s = s.where(~m, ts.dt.strftime("%d/%m/%Y %H:%M"))
    return s.where(ts.notna(), "")


def _labels(rng, qids: pd.Series):
    out = np.empty(len(qids), dtype=object)
    for q in QUEUES:
        m = (qids == q.queue_id).values
        if not m.any():
            continue
        variants = list(q.label_variants)
        p = np.array([0.80] + [0.20 / (len(variants) - 1)] * (len(variants) - 1))
        out[m] = rng.choice(variants, m.sum(), p=p)
    return out


def generate(out_dir=None, seed=config.SEED, verbose=True) -> dict:
    t0 = time.time()
    out_dir = out_dir or config.RAW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    dates = pd.date_range(config.PERIOD_START, config.PERIOD_END, freq="D")

    plan = build_plan(rng, dates)
    _log(f"WFM plan: {len(plan):,} queue-intervals", verbose)
    agents, tls, present = build_agents(rng, plan, dates)
    _log(f"agents: {len(agents)} across {len(tls)} teams", verbose)
    inter = simulate_interactions(rng, plan, agents, present, dates)
    inter = assign_customers(rng, inter, agents)
    customers = build_customers(rng, inter)
    cmap = customers.set_index("customer_num")
    _log(f"interactions: {len(inter):,}; customers: {len(customers):,}", verbose)

    qcode = {q.queue_id: q.code for q in QUEUES}
    inter["queue_code"] = inter.queue_id.map(qcode)
    inter["handled"] = ~inter.abandoned
    inter["handle_sec"] = inter.talk_sec + inter.hold_sec + inter.acw_sec
    inter["answer_ts"] = np.where(inter.channel.isin(["Voice", "Chat"]) & inter.handled,
                                  inter.start_ts + pd.to_timedelta(inter.wait_sec, unit="s"), pd.NaT)
    inter["answer_ts"] = pd.to_datetime(inter.answer_ts)
    if "first_response_ts" not in inter:
        inter["first_response_ts"] = pd.NaT
    rt = inter.channel.isin(["Voice", "Chat"])
    inter["end_ts"] = np.where(rt, np.where(inter.handled, inter.answer_ts + pd.to_timedelta(inter.talk_sec + inter.hold_sec, unit="s"),
                                            inter.start_ts + pd.to_timedelta(inter.wait_sec, unit="s")),
                               inter.first_response_ts + pd.to_timedelta(inter.talk_sec, unit="s"))
    inter["end_ts"] = pd.to_datetime(inter.end_ts)
    inter["agent_login"] = np.where(inter.agent_idx >= 0, agents.agent_login.values[np.maximum(inter.agent_idx, 0)], None)

    # unclosed agent sessions -> extreme recorded talk time on a few voice calls
    voice_h = inter.index[(inter.channel == "Voice") & inter.handled]
    unc = rng.choice(voice_h, size=int(len(voice_h) * 0.0032), replace=False)
    inter["true_talk_sec"] = inter.talk_sec
    inter.loc[unc, "talk_sec"] = inter.loc[unc, "talk_sec"] + rng.uniform(9000, 30000, len(unc)).round()
    inter.loc[unc, "end_ts"] = inter.loc[unc, "answer_ts"] + pd.to_timedelta(inter.loc[unc, "talk_sec"] + inter.loc[unc, "hold_sec"], unit="s")
    inter["unclosed"] = False
    inter.loc[unc, "unclosed"] = True

    ids = np.arange(len(inter))
    pref = inter.channel.map({"Voice": "CL", "Chat": "CH", "Email": "EM", "Back office": "BO"})
    inter["source_ref"] = pref + pd.Series(1_000_000 + ids).astype(str)

    files = {}
    # ---- dialler (voice)
    v = inter[inter.channel == "Voice"].copy()
    cust_v = cmap.loc[v.customer_num]
    dial = pd.DataFrame({
        "call_id": v.source_ref.values, "queue_label": _labels(rng, v.queue_id),
        "ani": cust_v.phone.values, "agent_login": v.agent_login.values,
        "call_start": _fmt(v.start_ts, rng, 0.08).values, "answer_time": _fmt(v.answer_ts, rng).values,
        "end_time": _fmt(v.end_ts, rng).values, "wait_sec": v.wait_sec.values,
        "talk_sec": v.talk_sec.values, "hold_sec": v.hold_sec.astype(float).values, "acw_sec": v.acw_sec.values,
        "abandoned": np.where(v.abandoned, "Y", "N"), "transferred": np.where(v.transferred, "Y", "N"),
    })
    m = (dial.abandoned == "N") & (rng.random(len(dial)) < 0.03)
    dial.loc[m, "hold_sec"] = np.nan                                      # missing hold time
    m = (dial.abandoned == "N") & (rng.random(len(dial)) < 0.004)
    dial.loc[m, "agent_login"] = None                                     # answered but agent not captured
    m = rng.random(len(dial)) < 0.001
    dial.loc[m, "wait_sec"] = -dial.loc[m, "wait_sec"].abs() - 1          # clock skew
    dup = dial.sample(frac=0.012, random_state=seed)                      # ingestion re-run duplicates
    dial = pd.concat([dial, dup]).sample(frac=1.0, random_state=seed + 1).reset_index(drop=True)
    files["dialler_calls.csv"] = dial

    # ---- chat platform
    c = inter[inter.channel == "Chat"].copy()
    cust_c = cmap.loc[c.customer_num]
    chat = pd.DataFrame({
        "chat_id": c.source_ref.values, "queue_label": _labels(rng, c.queue_id), "visitor_email": cust_c.email.values,
        "agent_login": c.agent_login.values, "started_at": _fmt(c.start_ts, rng).values,
        "first_response_at": _fmt(c.answer_ts, rng).values, "ended_at": _fmt(c.end_ts, rng).values,
        "wait_sec": c.wait_sec.values, "handle_sec": (c.talk_sec + c.acw_sec).values, "acw_sec": c.acw_sec.values,
        "abandoned": np.where(c.abandoned, "true", "false"), "transferred": np.where(c.transferred, "true", "false"),
    })
    dup = chat.sample(frac=0.008, random_state=seed + 2)
    chat = pd.concat([chat, dup]).reset_index(drop=True)
    files["chat_sessions.csv"] = chat

    # ---- email and back office
    for ch, fname, idcol in (("Email", "email_tickets.csv", "ticket_id"), ("Back office", "backoffice_cases.csv", "case_ref")):
        e = inter[inter.channel == ch].copy()
        cust_e = cmap.loc[e.customer_num]
        files[fname] = pd.DataFrame({
            idcol: e.source_ref.values, "mailbox" if ch == "Email" else "workqueue": _labels(rng, e.queue_id),
            "from_address" if ch == "Email" else "customer_phone": (cust_e.email if ch == "Email" else cust_e.phone).values,
            "agent_login": e.agent_login.values, "received_at": _fmt(e.start_ts, rng).values,
            "first_response_at": _fmt(e.first_response_ts, rng).values, "closed_at": _fmt(e.end_ts, rng).values,
            "business_wait_sec": e.wait_sec.values, "handle_sec": e.talk_sec.values,
        })

    # ---- CRM: customers, cases, status history
    files["crm_customers.csv"] = customers.drop(columns=["customer_num"])
    h = inter[inter.handled].copy()
    lab = np.empty(len(h), dtype=object)
    for canon, variants in RESOLUTION_LABELS.items():
        mm = (h.resolution == canon).values
        p = np.array([0.78] + [0.22 / (len(variants) - 1)] * (len(variants) - 1))
        lab[mm] = rng.choice(variants, mm.sum(), p=p)
    lab[rng.random(len(h)) < 0.04] = None                                  # disposition not captured
    created = h.answer_ts.fillna(h.first_response_ts)
    cases = pd.DataFrame({"case_id": "CS" + pd.Series(2_000_000 + np.arange(len(h))).astype(str).values,
                          "source_ref": h.source_ref.values, "channel": h.channel.values,
                          "customer_id": cmap.loc[h.customer_num].customer_id.values, "reason": h.reason.values,
                          "disposition_label": lab, "created_at": _fmt(created, rng).values})
    files["crm_cases.csv"] = cases

    # status history: one-to-many per case
    hist = []
    st = h.resolution.values
    t_end = h.end_ts.values.astype("datetime64[s]")
    case_ids = cases.case_id.values
    r = rng.random(len(h))
    later = rng.uniform(3600, 3 * 86400, len(h)).astype("timedelta64[s]")
    for status, path in (("Resolved", None), ("Escalated", None), ("Callback scheduled", None), ("Pending customer", None)):
        mm = st == status
        hist.append(pd.DataFrame({"case_id": case_ids[mm], "status": "Opened", "status_at": t_end[mm] - np.timedelta64(30, "s")}))
        if status == "Resolved":
            mid = mm & (r < 0.3)
            hist.append(pd.DataFrame({"case_id": case_ids[mid], "status": "In progress", "status_at": t_end[mid] - np.timedelta64(10, "s")}))
            hist.append(pd.DataFrame({"case_id": case_ids[mm], "status": "Resolved", "status_at": t_end[mm]}))
        else:
            hist.append(pd.DataFrame({"case_id": case_ids[mm], "status": status, "status_at": t_end[mm]}))
            res_later = mm & (r < (0.6 if status != "Pending customer" else 0.35))
            hist.append(pd.DataFrame({"case_id": case_ids[res_later], "status": "Resolved", "status_at": t_end[res_later] + later[res_later]}))
    hist = pd.concat(hist, ignore_index=True).sort_values(["case_id", "status_at"]).reset_index(drop=True)
    hist.insert(0, "history_id", "SH" + pd.Series(np.arange(len(hist))).astype(str))
    hist["status_at"] = pd.to_datetime(hist.status_at).dt.strftime("%Y-%m-%d %H:%M:%S")
    files["crm_case_status_history.csv"] = hist

    # ---- CSAT
    resp_p = np.where(h.channel.isin(["Email", "Back office"]), 0.10, 0.145)
    hs = h[rng.random(len(h)) < resp_p].copy()
    q_by = {q.queue_id: q for q in QUEUES}
    thr = hs.queue_id.map(lambda x: q_by[x].sl_threshold_sec).values
    qual = agents._quality.values[np.maximum(hs.agent_idx.values, 0)]
    latent = 4.5 - 0.55 * (hs.wait_sec.values > thr) - 1.15 * (hs.resolution.values != "Resolved") + 0.30 * qual + rng.normal(0, 0.72, len(hs))
    cr = SCENARIOS["chat_release_csat"]
    mm = (hs.queue_id == cr["queue"]).values & (hs.date.values >= cr["start"]) & (hs.date.values <= cr["end"])
    latent[mm] += cr["csat_shift"]
    score = np.clip(np.round(latent), 1, 5).astype(float)
    bad = rng.random(len(hs)) < 0.003
    score[bad] = rng.choice([0, 6, np.nan], bad.sum())                    # invalid survey values
    resp_at = hs.end_ts + pd.to_timedelta(rng.uniform(300, 2 * 86400, len(hs)), unit="s")
    files["csat_responses.csv"] = pd.DataFrame({"survey_id": "SV" + pd.Series(np.arange(len(hs))).astype(str).values,
                                                "source_ref": hs.source_ref.values, "channel": hs.channel.values,
                                                "score": score, "responded_at": _fmt(resp_at, rng).values})

    # ---- QA audits
    ha = h[(h.channel != "Back office") & (rng.random(len(h)) < 0.03)].copy()
    qq = agents._quality.values[np.maximum(ha.agent_idx.values, 0)]
    params = {}
    for pname, w in (("greeting", 0.6), ("verification", 1.0), ("resolution", 1.4), ("empathy", 1.1), ("compliance", 0.8)):
        params[pname] = np.clip(np.round(86 + 5 * qq * w + rng.normal(0, 7, len(ha))), 30, 100)
    total = np.round(np.mean(np.vstack(list(params.values())), axis=0), 1)
    fatal = rng.random(len(ha)) < (0.022 + 0.02 * (qq < -1))
    total = np.where(fatal, np.minimum(total, 50.0), total)
    files["qa_audits.csv"] = pd.DataFrame({"audit_id": "QA" + pd.Series(np.arange(len(ha))).astype(str).values,
                                           "source_ref": ha.source_ref.values, "agent_login": ha.agent_login.values,
                                           "audit_date": (ha.end_ts + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d").values,
                                           **params, "total_score": total, "fatal_error": np.where(fatal, "Y", "N")})

    # ---- WFM plan and staffed agents
    plan_out = plan[plan.handling | (plan.fc_volume > 0)].copy()
    plan_out["queue_code"] = plan_out.queue_id.map(qcode)
    plan_out["interval_start"] = plan_out.iv.map(_iv_label)
    files["wfm_plan.csv"] = plan_out[["date", "interval_start", "queue_code", "fc_volume", "fc_aht", "required", "scheduled"]].rename(
        columns={"fc_volume": "forecast_volume", "fc_aht": "forecast_aht_sec", "required": "required_agents", "scheduled": "scheduled_agents"}).round(2)
    st_out = plan[plan.handling].copy()
    st_out["queue_code"] = st_out.queue_id.map(qcode)
    st_out["interval_start"] = st_out.iv.map(_iv_label)
    files["wfm_staffed_interval.csv"] = st_out[["date", "interval_start", "queue_code", "staffed"]].rename(columns={"staffed": "staffed_agents"})

    # ---- agent sessions (login / logout); unclosed sessions have no logout
    sess = []
    unc_keys = set(zip(inter.loc[unc, "agent_idx"], inter.loc[unc, "day_idx"]))
    for j, a in agents.iterrows():
        h0, h1 = SHIFTS[a["shift"]]
        for d in np.flatnonzero(present[j]):
            day = dates[d]
            login = day + pd.Timedelta(hours=h0) + pd.Timedelta(minutes=float(rng.normal(-4, 5)))
            logout = day + pd.Timedelta(hours=h1) + pd.Timedelta(minutes=float(rng.normal(3, 7)))
            sess.append((a["agent_login"], day.date(), login, None if (j, d) in unc_keys else logout,
                         int(rng.integers(45, 75)), int(rng.choice([0, 0, 0, 30, 60]))))
    sess = pd.DataFrame(sess, columns=["agent_login", "date", "login_at", "logout_at", "aux_break_min", "aux_training_min"])
    sess.insert(0, "session_id", "SE" + pd.Series(np.arange(len(sess))).astype(str))
    sess["login_at"] = sess.login_at.dt.strftime("%Y-%m-%d %H:%M:%S")
    sess["logout_at"] = pd.to_datetime(sess.logout_at).dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    files["agent_sessions.csv"] = sess

    # ---- HR roster
    hr = agents.merge(tls[["team_leader_id", "team_leader_name"]], on="team_leader_id")
    files["hr_agents.csv"] = hr[["agent_id", "agent_login", "full_name", "site", "team_leader_id", "team_leader_name", "queue_code",
                                 "shift", "date_of_joining"]].assign(employment_status="Active")

    # ---- source system daily reports (what the dialler / chat platform says happened)
    srep = (inter[inter.channel.isin(["Voice", "Chat"])].groupby(["date", "queue_code", "channel"])
            .agg(offered=("source_ref", "size"), answered=("handled", "sum"), abandoned=("abandoned", "sum")).reset_index())
    files["source_daily_report.csv"] = srep

    files["holidays.csv"] = pd.DataFrame([{"date": d, "holiday": n, "volume_factor": f} for d, (n, f) in HOLIDAYS.items()])

    for name, df in files.items():
        df.to_csv(out_dir / name, index=False)

    # ground truth for tests and documentation (not used by the pipeline)
    truth = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"), "seed": seed,
        "interactions": int(len(inter)), "unclosed_sessions": int(len(unc)),
        "voice_duplicates": int(round(len(inter[inter.channel == 'Voice']) * 0.012)),
        "scenarios": {k: v.get("description") for k, v in SCENARIOS.items()},
        "true_handle_unclosed_median": float(inter.loc[unc, "true_talk_sec"].median()) if len(unc) else None,
        "files": {k: int(len(v)) for k, v in files.items()},
    }
    (out_dir / "_manifest.json").write_text(json.dumps(truth, indent=2, default=str))
    _log(f"wrote {len(files)} source extracts in {time.time() - t0:.1f}s", verbose)
    return truth


def stable_hash(value: str, salt: str = "oip") -> str:
    return hashlib.sha256((salt + str(value)).encode()).hexdigest()[:16]


if __name__ == "__main__":
    generate()
