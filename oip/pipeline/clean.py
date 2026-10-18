"""Cleaning pipeline: four channel extracts -> one conformed interaction table.

Each rule is a function with an ID, a plain-English description and the number
of rows it touched, so the effect on record counts can be audited and
reconciled. Rules marked APPROVED changed after review with the reporting team
(see the 'history' field) and are covered by tests.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from oip import config, db
from oip.pipeline.ingest import SALT
from oip.reference import QUEUES, RESOLUTION_LABELS

QUEUE_LABEL_MAP = {v.strip().lower(): q.queue_id for q in QUEUES for v in q.label_variants}
RESOLUTION_MAP = {v.strip().lower(): canon for canon, vs in RESOLUTION_LABELS.items() for v in vs}
Q = {q.queue_id: q for q in QUEUES}


@dataclass
class RuleLog:
    steps: list = field(default_factory=list)

    def add(self, rule_id, name, description, rows_before, rows_after, affected, decision="", history=""):
        self.steps.append({"rule_id": rule_id, "name": name, "description": description, "rows_before": int(rows_before),
                           "rows_after": int(rows_after), "rows_affected": int(affected), "decision": decision, "history": history})


def parse_ts(s: pd.Series) -> tuple[pd.Series, int]:
    iso = pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    alt = pd.to_datetime(s, format="%d/%m/%Y %H:%M", errors="coerce")       # day-first, no seconds
    return iso.fillna(alt), int((iso.isna() & alt.notna()).sum())


def shift_window(hour_float: pd.Series) -> pd.Series:
    return pd.Series(np.select([(hour_float >= 8) & (hour_float < 11), (hour_float >= 11) & (hour_float < 14.5),
                                (hour_float >= 14.5) & (hour_float < 23)], ["Morning", "General", "Evening"], "Night"),
                     index=hour_float.index)


def customer_key(customer_id: pd.Series) -> pd.Series:
    vals = customer_id.fillna("").values
    return pd.Series([("K" + hashlib.sha256((SALT + v).encode()).hexdigest()[:12]) if v else None for v in vals], index=customer_id.index)


def load_unified(log: RuleLog) -> pd.DataFrame:
    d = db.read_sql("SELECT * FROM stg_dialler_calls")
    c = db.read_sql("SELECT * FROM stg_chat_sessions")
    e = db.read_sql("SELECT * FROM stg_email_tickets")
    b = db.read_sql("SELECT * FROM stg_backoffice_cases")
    num = lambda s: pd.to_numeric(s, errors="coerce")
    frames = [
        pd.DataFrame({"source_system": "dialler", "source_ref": d.call_id, "channel": "Voice", "queue_label": d.queue_label,
                      "agent_login": d.agent_login, "id_key": d.ani_key, "id_kind": "phone", "start_raw": d.call_start,
                      "answer_raw": d.answer_time, "end_raw": d.end_time, "wait_sec": num(d.wait_sec), "talk_sec": num(d.talk_sec),
                      "hold_sec": num(d.hold_sec), "acw_sec": num(d.acw_sec), "abandoned": d.abandoned.eq("Y"),
                      "transferred": d.transferred.eq("Y")}),
        pd.DataFrame({"source_system": "chat", "source_ref": c.chat_id, "channel": "Chat", "queue_label": c.queue_label,
                      "agent_login": c.agent_login, "id_key": c.email_key, "id_kind": "email", "start_raw": c.started_at,
                      "answer_raw": c.first_response_at, "end_raw": c.ended_at, "wait_sec": num(c.wait_sec),
                      "talk_sec": num(c.handle_sec) - num(c.acw_sec), "hold_sec": 0.0, "acw_sec": num(c.acw_sec),
                      "abandoned": c.abandoned.eq("true"), "transferred": c.transferred.eq("true")}),
        pd.DataFrame({"source_system": "email", "source_ref": e.ticket_id, "channel": "Email", "queue_label": e.mailbox,
                      "agent_login": e.agent_login, "id_key": e.email_key, "id_kind": "email", "start_raw": e.received_at,
                      "answer_raw": e.first_response_at, "end_raw": e.closed_at, "wait_sec": num(e.business_wait_sec),
                      "talk_sec": num(e.handle_sec), "hold_sec": 0.0, "acw_sec": 0.0, "abandoned": False, "transferred": False}),
        pd.DataFrame({"source_system": "backoffice", "source_ref": b.case_ref, "channel": "Back office", "queue_label": b.workqueue,
                      "agent_login": b.agent_login, "id_key": b.phone_key, "id_kind": "phone", "start_raw": b.received_at,
                      "answer_raw": b.first_response_at, "end_raw": b.closed_at, "wait_sec": num(b.business_wait_sec),
                      "talk_sec": num(b.handle_sec), "hold_sec": 0.0, "acw_sec": 0.0, "abandoned": False, "transferred": False}),
    ]
    df = pd.concat(frames, ignore_index=True)
    log.add("R00", "Union channel extracts", "Conform dialler, chat, email and back-office extracts to one schema.",
            0, len(df), len(df))
    return df


def run_clean(verbose: bool = True) -> tuple[pd.DataFrame, RuleLog]:
    t0 = time.time()
    log = RuleLog()
    df = load_unified(log)

    # R01 timestamps
    n = len(df)
    df["start_ts"], alt = parse_ts(df.start_raw)
    df["answer_ts"], _ = parse_ts(df.answer_raw)
    df["end_ts"], _ = parse_ts(df.end_raw)
    bad = df.start_ts.isna()
    log.add("R01", "Parse timestamps", "Parse ISO timestamps; parse dd/mm/yyyy HH:MM day-first. Rows with no parseable start are quarantined.",
            n, n - bad.sum(), alt, decision=f"{alt:,} day-first timestamps converted; {int(bad.sum())} unparseable rows quarantined")
    df = df[~bad].copy()

    # R02 exact duplicates by composite business key (done early so later counts are true)
    n = len(df)
    dup = df.duplicated(subset=["source_system", "source_ref", "start_raw"], keep="first")
    df = df[~dup].copy()
    log.add("R02", "Remove duplicates", "Drop repeated records with the same source system, source reference and start time (ingestion re-runs).",
            n, len(df), dup.sum(), decision="Composite business key: source_system + source_ref + start time")

    # R03 queue labels
    n = len(df)
    df["queue_id"] = df.queue_label.str.strip().str.lower().map(QUEUE_LABEL_MAP)
    unmapped = df.queue_id.isna()
    changed = (df.queue_label.str.strip() != df.queue_id.map(lambda x: Q[x].code if isinstance(x, str) else None)).sum()
    log.add("R03", "Standardise queue names", "Map every label variant to the canonical queue using the mapping dictionary agreed with reporting.",
            n, n - unmapped.sum(), changed, decision=f"{len(QUEUE_LABEL_MAP)} variants -> {len(QUEUES)} queues; unmapped rows quarantined: {int(unmapped.sum())}")
    df = df[~unmapped].copy()
    df["client_id"] = df.queue_id.map(lambda x: Q[x].client_id)

    # R04 negative waits
    neg = df.wait_sec < 0
    df.loc[neg, "wait_sec"] = 0.0
    df["wait_corrected"] = neg
    log.add("R04", "Correct negative waits", "Negative wait times come from clock skew between dialler nodes; set to 0 and flag.",
            len(df), len(df), neg.sum())

    # R05 hold imputation (median by queue, skewed distribution)
    df["handled"] = ~df.abandoned
    miss = df.hold_sec.isna() & df.handled
    med = df[df.handled & df.hold_sec.notna()].groupby("queue_id").hold_sec.median()
    df.loc[miss, "hold_sec"] = df.loc[miss, "queue_id"].map(med)
    df["hold_sec"] = df.hold_sec.fillna(0.0)
    df["hold_imputed"] = miss
    log.add("R05", "Impute missing hold time", "Hold time is right-skewed, so missing values take the queue median for answered calls, not the mean.",
            len(df), len(df), miss.sum(), decision="Median by queue; imputed rows flagged hold_imputed")

    # agents
    hr = db.read_sql("SELECT agent_id, agent_login FROM stg_hr_agents")
    df["agent_id"] = df.agent_login.map(dict(zip(hr.agent_login, hr.agent_id)))
    no_agent = df.handled & df.agent_id.isna()
    df.loc[no_agent, "agent_id"] = "UNASSIGNED"
    df["agent_missing"] = no_agent
    log.add("R06", "Keep answered contacts with no agent", "Answered contacts where the dialler did not capture the agent are kept as UNASSIGNED; abandoned contacts legitimately have no agent.",
            len(df), len(df), no_agent.sum(),
            decision="Retained and flagged agent_missing",
            history="v1 dropped answered rows with a blank agent_login; reconciliation on three sample dates showed answered counts below the dialler report, so the rule was changed (approved by reporting lead).")

    # R07 derived attributes
    st = df.start_ts
    df["date"] = st.dt.date
    df["date_key"] = st.dt.strftime("%Y%m%d").astype(int)
    df["hour"] = st.dt.hour
    hf = st.dt.hour + st.dt.minute / 60
    df["interval_idx"] = (st.dt.hour * 2 + (st.dt.minute >= 30)).astype(int)
    df["weekday"] = st.dt.day_name().str[:3]
    df["shift_window"] = shift_window(hf)
    log.add("R07", "Derive time attributes", "Date, hour, 30-minute interval, weekday and shift window from the start time.",
            len(df), len(df), len(df))

    # handle and outliers (IQR, investigated before treatment)
    df["handle_sec"] = np.where(df.handled, df.talk_sec.fillna(0) + df.hold_sec + df.acw_sec.fillna(0), 0.0)
    hh = df[df.handled]
    stats = hh.groupby("queue_id").handle_sec.quantile([0.25, 0.75, 0.99]).unstack()
    stats.columns = ["q1", "q3", "p99"]
    stats["upper"] = stats.q3 + 3 * (stats.q3 - stats.q1)
    upper = df.queue_id.map(stats.upper)
    outlier = df.handled & (df.handle_sec > upper)
    sess = db.read_sql("SELECT agent_login, date, logout_at FROM stg_agent_sessions")
    sess["unclosed"] = sess.logout_at.isna() | (sess.logout_at == "")
    unclosed_days = set(zip(sess.loc[sess.unclosed, "agent_login"], sess.loc[sess.unclosed, "date"]))
    key = list(zip(df.agent_login, df.date.astype(str)))
    in_unclosed = pd.Series([k in unclosed_days for k in key], index=df.index)
    unclosed = outlier & in_unclosed & (df.handle_sec > config.UNCLOSED_SESSION_SEC)
    p99 = df.queue_id.map(stats.p99)
    excess = (df.handle_sec - p99).where(unclosed, 0)
    df["talk_sec_raw"] = df.talk_sec
    df.loc[unclosed, "talk_sec"] = (df.loc[unclosed, "talk_sec"] - excess[unclosed]).clip(lower=30)
    df["handle_sec"] = np.where(df.handled, df.talk_sec.fillna(0) + df.hold_sec + df.acw_sec.fillna(0), 0.0)
    df["unclosed_session"] = unclosed
    df["long_handle_reviewed"] = outlier & ~unclosed
    log.add("R08", "Treat unclosed-session outliers", "IQR (Q3 + 3xIQR by queue) flags extreme handle times. Those over 2 hours on an agent-day with no logout event are unclosed sessions, not long calls; capped at the queue P99. Other extremes are kept.",
            len(df), len(df), unclosed.sum(),
            decision=f"{int(outlier.sum())} extreme handle times; {int(unclosed.sum())} matched unclosed sessions and were capped; {int((outlier & ~unclosed).sum())} kept as genuine",
            history="Capping rule approved by mentor after the session-log investigation; before that, outliers were only flagged.")

    # short abandons and service level flags
    df["short_abandon"] = df.abandoned & (df.wait_sec <= config.SHORT_ABANDON_SEC)
    thr = df.queue_id.map(lambda x: Q[x].sl_threshold_sec)
    df["sl_threshold_sec"] = thr
    df["within_sl"] = df.handled & (df.wait_sec <= thr)
    df["sl_eligible"] = ~df.short_abandon
    df["realtime"] = df.channel.isin(["Voice", "Chat"])
    log.add("R09", "Flag short abandons and service level", f"Abandons within {config.SHORT_ABANDON_SEC}s are excluded from SLA and abandon-rate denominators; answered within the queue threshold count as within SLA.",
            len(df), len(df), df.short_abandon.sum(),
            history="Short-abandon exclusion aligned with the operations month-end method after a mismatch in SLA attainment was found.")

    # CRM link: case, reason, disposition (with rule-based imputation)
    cases = db.read_sql("SELECT case_id, source_ref, customer_id, reason, disposition_label FROM stg_crm_cases")
    hist = db.read_sql("""
        WITH ranked AS (
          SELECT case_id, status, ROW_NUMBER() OVER (PARTITION BY case_id ORDER BY status_at DESC, history_id DESC) AS rn
          FROM stg_crm_case_status_history)
        SELECT case_id, status AS latest_status FROM ranked WHERE rn = 1""")
    cases = cases.merge(hist, on="case_id", how="left")
    cases["resolution"] = cases.disposition_label.str.strip().str.lower().map(RESOLUTION_MAP)
    miss = cases.resolution.isna()
    imputed = cases.loc[miss, "latest_status"].where(cases.loc[miss, "latest_status"].isin(list(RESOLUTION_LABELS)), "Unknown")
    cases.loc[miss, "resolution"] = imputed
    cases["disposition_imputed"] = miss
    df = df.merge(cases[["source_ref", "case_id", "customer_id", "reason", "resolution", "disposition_imputed", "latest_status"]],
                  on="source_ref", how="left")
    df["disposition_imputed"] = df.disposition_imputed.fillna(False).astype(bool)
    log.add("R10", "Standardise and impute dispositions", "Map messy CRM labels to four outcomes; blank labels take the case's latest status from status history (ROW_NUMBER), else 'Unknown'.",
            len(df), len(df), int(miss.sum()), decision=f"{int(miss.sum())} blank labels imputed; {int((imputed == 'Unknown').sum())} left Unknown")

    # customer identity resolution: CRM id first, else hashed phone/email from the CRM master
    cust = db.read_sql("SELECT customer_id, phone_key, email_key FROM stg_crm_customers")
    by_phone = dict(zip(cust.phone_key, cust.customer_id))
    by_email = dict(zip(cust.email_key, cust.customer_id))
    resolved = df.customer_id.copy()
    m = resolved.isna()
    resolved[m] = np.where(df.loc[m, "id_kind"] == "phone", df.loc[m, "id_key"].map(by_phone), df.loc[m, "id_key"].map(by_email))
    df["customer_key"] = customer_key(resolved)
    unres = df.customer_key.isna()
    df.loc[unres, "customer_key"] = "U" + df.loc[unres, "id_key"].fillna("unknown").str[:12]
    log.add("R11", "Resolve customer identity", "Link contacts to one customer key through the CRM case, or the hashed phone/email in the CRM master (abandoned calls have no case).",
            len(df), len(df), int(m.sum()), decision=f"{int(unres.sum())} contacts could not be matched and keep a channel-level key")

    keep = ["source_system", "source_ref", "channel", "queue_id", "client_id", "agent_id", "customer_key", "case_id",
            "start_ts", "answer_ts", "end_ts", "date", "date_key", "hour", "interval_idx", "weekday", "shift_window",
            "handled", "abandoned", "short_abandon", "realtime", "wait_sec", "talk_sec", "hold_sec", "acw_sec", "handle_sec",
            "sl_threshold_sec", "within_sl", "sl_eligible", "transferred", "reason", "resolution", "latest_status",
            "disposition_imputed", "hold_imputed", "wait_corrected", "agent_missing", "unclosed_session", "long_handle_reviewed",
            "talk_sec_raw"]
    out = df[keep].sort_values("start_ts").reset_index(drop=True)
    if verbose:
        print(f"  [clean] {len(out):,} interactions after {len(log.steps)} rules in {time.time() - t0:.1f}s", flush=True)
    return out, log
