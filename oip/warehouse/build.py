"""Warehouse build: dimensions, facts, FCR, indexes and reporting layer.

Order matters: dimensions -> facts -> derived columns (FCR via window function)
-> indexes -> reporting tables (interval cube, agent-day) that the dashboard,
Power BI export and analytics read.
"""
from __future__ import annotations

import time
from datetime import timedelta

import numpy as np
import pandas as pd

from oip import config, db
from oip.pipeline.clean import RuleLog, customer_key
from oip.reference import CLIENTS, HOLIDAYS, QUEUE_BY_CODE, QUEUES

SCHEMA = (config.ROOT / "oip" / "warehouse" / "schema.sql").read_text()

REPORTING_SQL = f"""
DROP TABLE IF EXISTS rpt_interval_cube;
CREATE TABLE rpt_interval_cube AS
WITH i AS (
  SELECT date_key, interval_idx, queue_id,
         COUNT(*)                                  AS offered,
         SUM(realtime)                             AS rt_offered,
         SUM(handled)                              AS handled,
         SUM(abandoned)                            AS abandoned,
         SUM(short_abandon)                        AS short_abandoned,
         SUM(within_sl)                            AS sl_num,
         SUM(sl_eligible)                          AS sl_den,
         SUM(CASE WHEN handled = 1 AND realtime = 1 THEN wait_sec ELSE 0 END) AS asa_num,
         SUM(CASE WHEN handled = 1 AND realtime = 1 THEN 1 ELSE 0 END)        AS asa_den,
         SUM(talk_sec) AS talk_sec, SUM(hold_sec) AS hold_sec, SUM(acw_sec) AS acw_sec, SUM(handle_sec) AS handle_sec,
         SUM(transferred) AS transferred, SUM(fcr) AS fcr_num, SUM(fcr_eligible) AS fcr_den
  FROM fact_interaction GROUP BY date_key, interval_idx, queue_id),
c AS (
  SELECT f.date_key, f.interval_idx, f.queue_id, COUNT(*) AS csat_resp,
         SUM(CASE WHEN s.score >= {config.CSAT_TOP_BOX} THEN 1 ELSE 0 END) AS csat_top2, SUM(s.score) AS csat_sum
  FROM fact_csat s JOIN fact_interaction f ON f.interaction_id = s.interaction_id
  GROUP BY f.date_key, f.interval_idx, f.queue_id),
k AS (
  SELECT date_key, interval_idx, queue_id FROM i
  UNION SELECT date_key, interval_idx, queue_id FROM fact_wfm_interval)
SELECT k.date_key, k.interval_idx, k.queue_id,
       COALESCE(i.offered, 0) AS offered, COALESCE(i.rt_offered, 0) AS rt_offered, COALESCE(i.handled, 0) AS handled,
       COALESCE(i.abandoned, 0) AS abandoned, COALESCE(i.short_abandoned, 0) AS short_abandoned,
       COALESCE(i.sl_num, 0) AS sl_num, COALESCE(i.sl_den, 0) AS sl_den,
       ROUND(COALESCE(i.asa_num, 0), 1) AS asa_num, COALESCE(i.asa_den, 0) AS asa_den,
       ROUND(COALESCE(i.talk_sec, 0)) AS talk_sec, ROUND(COALESCE(i.hold_sec, 0)) AS hold_sec,
       ROUND(COALESCE(i.acw_sec, 0)) AS acw_sec, ROUND(COALESCE(i.handle_sec, 0)) AS handle_sec,
       COALESCE(i.transferred, 0) AS transferred, COALESCE(i.fcr_num, 0) AS fcr_num, COALESCE(i.fcr_den, 0) AS fcr_den,
       COALESCE(c.csat_resp, 0) AS csat_resp, COALESCE(c.csat_top2, 0) AS csat_top2, COALESCE(c.csat_sum, 0) AS csat_sum,
       ROUND(COALESCE(w.forecast_volume, 0), 2) AS forecast_volume,
       ROUND(COALESCE(w.forecast_volume * w.forecast_aht_sec, 0), 1) AS fc_aht_x_vol,
       COALESCE(w.required_agents, 0) AS required_agents, COALESCE(w.scheduled_agents, 0) AS scheduled_agents,
       COALESCE(w.staffed_agents, 0) AS staffed_agents,
       COALESCE(w.staffed_agents, 0) * 1800 AS staffed_sec, COALESCE(w.scheduled_agents, 0) * 1800 AS scheduled_sec,
       COALESCE(w.staffed_agents, 0) * 1800 * (SELECT concurrency FROM dim_queue dq WHERE dq.queue_id = k.queue_id) AS capacity_sec,
       ROUND(ABS(COALESCE(i.offered, 0) - COALESCE(w.forecast_volume, 0)), 2) AS abs_fc_err
FROM k
LEFT JOIN i ON i.date_key = k.date_key AND i.interval_idx = k.interval_idx AND i.queue_id = k.queue_id
LEFT JOIN c ON c.date_key = k.date_key AND c.interval_idx = k.interval_idx AND c.queue_id = k.queue_id
LEFT JOIN fact_wfm_interval w ON w.date_key = k.date_key AND w.interval_idx = k.interval_idx AND w.queue_id = k.queue_id;
CREATE INDEX ix_cube_q_d ON rpt_interval_cube(queue_id, date_key);

DROP TABLE IF EXISTS rpt_agent_day;
CREATE TABLE rpt_agent_day AS
WITH h AS (
  SELECT agent_id, date_key, queue_id, COUNT(*) AS handled, SUM(handle_sec) AS handle_sec, SUM(talk_sec) AS talk_sec,
         SUM(hold_sec) AS hold_sec, SUM(acw_sec) AS acw_sec, SUM(transferred) AS transferred,
         SUM(fcr) AS fcr_num, SUM(fcr_eligible) AS fcr_den
  FROM fact_interaction WHERE handled = 1 AND agent_id <> 'UNASSIGNED' GROUP BY agent_id, date_key, queue_id),
c AS (
  SELECT f.agent_id, f.date_key, COUNT(*) AS csat_resp, SUM(CASE WHEN s.score >= {config.CSAT_TOP_BOX} THEN 1 ELSE 0 END) AS csat_top2
  FROM fact_csat s JOIN fact_interaction f ON f.interaction_id = s.interaction_id GROUP BY f.agent_id, f.date_key),
q AS (
  SELECT f.agent_id, f.date_key, COUNT(*) AS qa_audits, SUM(a.total_score) AS qa_sum, SUM(a.fatal_error) AS qa_fatal
  FROM fact_qa a JOIN fact_interaction f ON f.interaction_id = a.interaction_id GROUP BY f.agent_id, f.date_key),
s AS (SELECT agent_id, date_key, logged_in_sec, aux_sec FROM fact_agent_session)
SELECT h.*, COALESCE(c.csat_resp, 0) AS csat_resp, COALESCE(c.csat_top2, 0) AS csat_top2,
       COALESCE(q.qa_audits, 0) AS qa_audits, COALESCE(q.qa_sum, 0) AS qa_sum, COALESCE(q.qa_fatal, 0) AS qa_fatal,
       COALESCE(s.logged_in_sec, 0) AS logged_in_sec, COALESCE(s.aux_sec, 0) AS aux_sec
FROM h LEFT JOIN c ON c.agent_id = h.agent_id AND c.date_key = h.date_key
LEFT JOIN q ON q.agent_id = h.agent_id AND q.date_key = h.date_key
LEFT JOIN s ON s.agent_id = h.agent_id AND s.date_key = h.date_key;
CREATE INDEX ix_ad ON rpt_agent_day(agent_id, date_key);

DROP VIEW IF EXISTS rpt_queue_day;
CREATE VIEW rpt_queue_day AS
SELECT c.date_key, c.queue_id, q.queue_code, q.client_id, q.channel,
       SUM(offered) AS offered, SUM(handled) AS handled, SUM(sl_num) AS sl_num, SUM(sl_den) AS sl_den,
       ROUND(SUM(sl_num) * 1.0 / NULLIF(SUM(sl_den), 0), 4) AS service_level,
       ROUND((SUM(abandoned) - SUM(short_abandoned)) * 1.0 / NULLIF(SUM(rt_offered) - SUM(short_abandoned), 0), 4) AS abandon_rate,
       ROUND(SUM(handle_sec) / NULLIF(SUM(handled), 0), 1) AS aht_sec,
       ROUND(SUM(fcr_num) * 1.0 / NULLIF(SUM(fcr_den), 0), 4) AS fcr,
       ROUND(SUM(csat_top2) * 1.0 / NULLIF(SUM(csat_resp), 0), 4) AS csat,
       ROUND(SUM(staffed_agents) * 1.0 / NULLIF(SUM(required_agents), 0), 4) AS staffing_ratio
FROM rpt_interval_cube c JOIN dim_queue q ON q.queue_id = c.queue_id
GROUP BY c.date_key, c.queue_id;
"""

FCR_SQL = f"""
DROP TABLE IF EXISTS _fi_next;
CREATE TABLE _fi_next AS
SELECT interaction_id,
       LEAD(start_ts) OVER (PARTITION BY client_id, customer_key ORDER BY start_ts, interaction_id) AS next_contact_ts
FROM fact_interaction;
CREATE INDEX ix_fi_next ON _fi_next(interaction_id);
UPDATE fact_interaction SET next_contact_ts = (SELECT n.next_contact_ts FROM _fi_next n WHERE n.interaction_id = fact_interaction.interaction_id);
UPDATE fact_interaction SET
  repeat_7d    = CASE WHEN next_contact_ts IS NOT NULL AND julianday(next_contact_ts) - julianday(start_ts) <= {config.FCR_WINDOW_DAYS} THEN 1 ELSE 0 END,
  fcr_eligible = CASE WHEN handled = 1 AND start_ts < datetime('{config.PERIOD_END.isoformat()} 23:59:59', '-{config.FCR_WINDOW_DAYS} days') THEN 1 ELSE 0 END;
UPDATE fact_interaction SET fcr = CASE WHEN fcr_eligible = 1 AND repeat_7d = 0 THEN 1 ELSE 0 END;
DROP TABLE _fi_next;
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS ix_fi_date       ON fact_interaction(date_key);
CREATE INDEX IF NOT EXISTS ix_fi_queue_date ON fact_interaction(queue_id, date_key);
CREATE INDEX IF NOT EXISTS ix_fi_agent      ON fact_interaction(agent_id, date_key);
CREATE INDEX IF NOT EXISTS ix_fi_customer   ON fact_interaction(client_id, customer_key, start_ts);
CREATE INDEX IF NOT EXISTS ix_fi_case       ON fact_interaction(case_id);
CREATE INDEX IF NOT EXISTS ix_cs_case       ON fact_case_status(case_id, status_at);
CREATE INDEX IF NOT EXISTS ix_csat_int      ON fact_csat(interaction_id);
CREATE INDEX IF NOT EXISTS ix_qa_int        ON fact_qa(interaction_id);
"""


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.strftime("%Y-%m-%d %H:%M:%S").where(s.notna(), None)


def build_warehouse(clean: pd.DataFrame, log: RuleLog, verbose=True) -> dict:
    t0 = time.time()
    db.executescript(SCHEMA)

    # ---- dimensions
    dates = pd.date_range(config.PERIOD_START, config.PERIOD_END, freq="D")
    dd = pd.DataFrame({"date_key": dates.strftime("%Y%m%d").astype(int), "date": dates.strftime("%Y-%m-%d"),
                       "day_of_month": dates.day, "weekday_num": dates.dayofweek + 1, "weekday": dates.day_name().str[:3],
                       "iso_week": dates.isocalendar().week.values.astype(int), "month_num": dates.month,
                       "month_name": dates.month_name(), "is_weekend": (dates.dayofweek >= 5).astype(int)})
    dd["is_holiday"] = [int(d.date() in HOLIDAYS) for d in dates]
    dd["holiday_name"] = [HOLIDAYS.get(d.date(), (None,))[0] for d in dates]
    db.write(dd, "dim_date", if_exists="append")
    iv = pd.DataFrame({"interval_idx": range(48)})
    iv["label"] = iv.interval_idx.map(lambda i: f"{i // 2:02d}:{'30' if i % 2 else '00'}")
    iv["hour"] = iv.interval_idx // 2
    from oip.pipeline.clean import shift_window
    iv["shift_window"] = shift_window(iv.interval_idx / 2.0)
    db.write(iv, "dim_interval", if_exists="append")
    db.write(pd.DataFrame(CLIENTS), "dim_client", if_exists="append")
    db.write(pd.DataFrame([{"queue_id": q.queue_id, "queue_code": q.code, "queue_name": q.name, "client_id": q.client_id,
                            "channel": q.channel, "open_hour": q.open_hour, "close_hour": q.close_hour,
                            "sl_threshold_sec": q.sl_threshold_sec, "sl_target": q.sl_target, "aht_target_sec": q.aht_target_sec,
                            "abandon_target": q.abandon_target, "concurrency": q.concurrency} for q in QUEUES]), "dim_queue", if_exists="append")
    hr = db.read_sql("SELECT * FROM stg_hr_agents")
    db.write(hr[["team_leader_id", "team_leader_name", "queue_code", "shift"]].drop_duplicates("team_leader_id"),
             "dim_team_leader", if_exists="append")
    doj = pd.to_datetime(hr.date_of_joining)
    ten = (pd.Timestamp(config.PERIOD_END) - doj).dt.days
    agents = pd.DataFrame({"agent_id": hr.agent_id, "agent_login": hr.agent_login, "full_name": hr.full_name, "site": hr.site,
                           "team_leader_id": hr.team_leader_id, "queue_id": hr.queue_code.map(lambda c: QUEUE_BY_CODE[c].queue_id),
                           "shift": hr["shift"], "date_of_joining": hr.date_of_joining, "tenure_days_at_end": ten,
                           "tenure_band": pd.cut(ten, [-1, 90, 180, 365, 10_000], labels=["0-3m", "3-6m", "6-12m", "12m+"]).astype(str)})
    agents = pd.concat([agents, pd.DataFrame([{"agent_id": "UNASSIGNED", "agent_login": None, "full_name": "Unassigned (not captured)",
                                               "site": None, "team_leader_id": None, "queue_id": None, "shift": None,
                                               "date_of_joining": None, "tenure_days_at_end": None, "tenure_band": "n/a"}])])
    db.write(agents, "dim_agent", if_exists="append")
    cu = db.read_sql("SELECT customer_id, client_code, name_masked, phone_masked, email_masked, city FROM stg_crm_customers")
    cu["customer_key"] = customer_key(cu.customer_id)
    db.write(cu.drop(columns=["customer_id"]).drop_duplicates("customer_key"), "dim_customer", if_exists="append")

    # ---- fact_interaction
    f = clean.copy()
    f.insert(0, "interaction_id", np.arange(1, len(f) + 1))
    for c in ("start_ts", "answer_ts", "end_ts"):
        f[c] = _ts(f[c])
    bools = ["handled", "abandoned", "short_abandon", "realtime", "within_sl", "sl_eligible", "transferred", "disposition_imputed",
             "hold_imputed", "wait_corrected", "agent_missing", "unclosed_session", "long_handle_reviewed"]
    for c in bools:
        f[c] = f[c].astype(int)
    for c in ("talk_sec", "hold_sec", "acw_sec", "handle_sec", "wait_sec", "talk_sec_raw"):
        f[c] = f[c].astype(float).round(1)
    f = f.drop(columns=["date"])
    f["next_contact_ts"], f["repeat_7d"], f["fcr_eligible"], f["fcr"] = None, 0, 0, 0
    db.write(f, "fact_interaction", if_exists="append")
    db.executescript(INDEX_SQL)
    db.executescript(FCR_SQL)
    ref = f[["interaction_id", "source_ref", "case_id"]]

    # ---- case status history (one-to-many)
    hist = db.read_sql("SELECT history_id, case_id, status, status_at FROM stg_crm_case_status_history")
    hist = hist.merge(ref.dropna(subset=["case_id"])[["case_id", "interaction_id"]], on="case_id", how="inner")
    db.write(hist[["history_id", "case_id", "interaction_id", "status", "status_at"]], "fact_case_status", if_exists="append")

    # ---- CSAT (R12: invalid scores dropped)
    cs = db.read_sql("SELECT survey_id, source_ref, score, responded_at FROM stg_csat_responses")
    cs["score"] = pd.to_numeric(cs.score, errors="coerce")
    valid = cs.score.between(1, 5)
    log.add("R12", "Drop invalid survey scores", "CSAT scores must be integers 1-5; blanks and out-of-range values (0, 6) are survey-tool errors.",
            len(cs), int(valid.sum()), int((~valid).sum()))
    cs = cs[valid].merge(ref[["source_ref", "interaction_id"]], on="source_ref", how="inner")
    cs["score"] = cs.score.astype(int)
    db.write(cs[["survey_id", "interaction_id", "score", "responded_at"]], "fact_csat", if_exists="append")

    # ---- QA
    qa = db.read_sql("SELECT * FROM stg_qa_audits")
    qa = qa.merge(ref[["source_ref", "interaction_id"]], on="source_ref", how="inner")
    qa["agent_id"] = qa.agent_login.map(dict(zip(hr.agent_login, hr.agent_id))).fillna("UNASSIGNED")
    for c in ("greeting", "verification", "resolution", "empathy", "compliance", "total_score"):
        qa[c] = pd.to_numeric(qa[c])
    qa["fatal_error"] = qa.fatal_error.eq("Y").astype(int)
    db.write(qa[["audit_id", "interaction_id", "agent_id", "audit_date", "greeting", "verification", "resolution", "empathy",
                 "compliance", "total_score", "fatal_error"]], "fact_qa", if_exists="append")

    # ---- WFM
    plan = db.read_sql("SELECT * FROM stg_wfm_plan")
    stf = db.read_sql("SELECT * FROM stg_wfm_staffed_interval")
    w = plan.merge(stf[["date", "interval_start", "queue_code", "staffed_agents"]], on=["date", "interval_start", "queue_code"], how="left")
    w["date_key"] = w.date.str.replace("-", "").astype(int)
    w["interval_idx"] = w.interval_start.str[:2].astype(int) * 2 + (w.interval_start.str[3:5] == "30").astype(int)
    w["queue_id"] = w.queue_code.map(lambda c: QUEUE_BY_CODE[c].queue_id)
    for c in ("forecast_volume", "forecast_aht_sec"):
        w[c] = pd.to_numeric(w[c])
    for c in ("required_agents", "scheduled_agents", "staffed_agents"):
        w[c] = pd.to_numeric(w[c]).fillna(0).astype(int)
    db.write(w[["date_key", "interval_idx", "queue_id", "forecast_volume", "forecast_aht_sec", "required_agents", "scheduled_agents",
                "staffed_agents"]], "fact_wfm_interval", if_exists="append")

    # ---- sessions
    se = db.read_sql("SELECT * FROM stg_agent_sessions")
    se["agent_id"] = se.agent_login.map(dict(zip(hr.agent_login, hr.agent_id)))
    se["date_key"] = se.date.str.replace("-", "").astype(int)
    li = pd.to_datetime(se.login_at)
    lo = pd.to_datetime(se.logout_at.replace("", None))
    se["unclosed"] = lo.isna().astype(int)
    shift_len = 8.5 * 3600
    se["logged_in_sec"] = (lo - li).dt.total_seconds().fillna(shift_len)
    se["aux_sec"] = (pd.to_numeric(se.aux_break_min) + pd.to_numeric(se.aux_training_min)) * 60
    db.write(se.rename(columns={"login_at": "login_ts", "logout_at": "logout_ts"})[
        ["session_id", "agent_id", "date_key", "login_ts", "logout_ts", "logged_in_sec", "aux_sec", "unclosed"]], "fact_agent_session", if_exists="append")

    # ---- reporting layer
    db.executescript(REPORTING_SQL)
    db.write(pd.DataFrame(log.steps), "gov_cleaning_log")
    counts = db.read_sql("""SELECT 'fact_interaction' t, COUNT(*) n FROM fact_interaction UNION ALL SELECT 'fact_case_status', COUNT(*) FROM fact_case_status
        UNION ALL SELECT 'fact_csat', COUNT(*) FROM fact_csat UNION ALL SELECT 'fact_qa', COUNT(*) FROM fact_qa
        UNION ALL SELECT 'fact_wfm_interval', COUNT(*) FROM fact_wfm_interval UNION ALL SELECT 'rpt_interval_cube', COUNT(*) FROM rpt_interval_cube
        UNION ALL SELECT 'rpt_agent_day', COUNT(*) FROM rpt_agent_day""")
    if verbose:
        print("  [warehouse] " + ", ".join(f"{r.t} {r.n:,}" for r in counts.itertuples()) + f" ({time.time() - t0:.1f}s)", flush=True)
    return dict(zip(counts.t, counts.n.astype(int)))
