"""Read-only SQL lab with guard rails and the saved queries from the internship's SQL work."""
from __future__ import annotations

import re
import sqlite3
import time

from oip import db

MAX_ROWS = 1000
TIMEOUT_S = 6.0
BLOCKED = re.compile(r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|begin|commit)\b", re.I)


class SQLError(ValueError):
    pass


def check(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise SQLError("Enter a query.")
    if ";" in s:
        raise SQLError("One statement at a time.")
    if not re.match(r"^(select|with|explain)\b", s, re.I):
        raise SQLError("Only SELECT, WITH and EXPLAIN statements are allowed in the SQL lab.")
    if BLOCKED.search(re.sub(r"'[^']*'", "''", s)):
        raise SQLError("This statement contains a keyword that is not allowed on the read-only connection.")
    if re.search(r"\b(stg_|gov_load_log)", s, re.I):
        raise SQLError("Staging tables are blocked here (GOV-01): query the warehouse (dim_, fact_, rpt_) instead.")
    return s


def run(sql: str) -> dict:
    s = check(sql)
    with db.readonly_connection() as con:
        deadline = time.time() + TIMEOUT_S
        con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20_000)
        t0 = time.time()
        try:
            cur = con.execute(s)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_ROWS + 1)
        except sqlite3.OperationalError as e:
            msg = "Query stopped: it ran longer than 6 seconds." if "interrupted" in str(e) else str(e)
            raise SQLError(msg)
        elapsed = (time.time() - t0) * 1000
        plan = []
        if not s.lower().startswith("explain"):
            try:
                plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + s).fetchall()]
            except sqlite3.Error:
                plan = []
    truncated = len(rows) > MAX_ROWS
    return {"columns": cols, "rows": [list(r) for r in rows[:MAX_ROWS]], "row_count": min(len(rows), MAX_ROWS),
            "truncated": truncated, "elapsed_ms": round(elapsed, 1), "plan": plan}


SAVED = [
    {"id": "daily-volume", "title": "Daily volume, AHT and talk time by queue", "log": "05-Jun",
     "note": "Aggregation with GROUP BY and HAVING; filter rows with WHERE before aggregating, groups with HAVING after.",
     "sql": """SELECT d.date, q.queue_code,
       COUNT(*)                                   AS offered,
       SUM(f.handled)                             AS handled,
       ROUND(SUM(f.handle_sec) / SUM(f.handled))  AS aht_sec,
       ROUND(SUM(f.talk_sec) / 3600.0, 1)         AS talk_hours
FROM fact_interaction f
JOIN dim_queue q ON q.queue_id = f.queue_id
JOIN dim_date  d ON d.date_key = f.date_key
WHERE f.channel = 'Voice'
GROUP BY d.date, q.queue_code
HAVING COUNT(*) > 100
ORDER BY d.date DESC, offered DESC
LIMIT 50"""},
    {"id": "agent-day", "title": "Agent daily performance (four-table join)", "log": "06-Jun",
     "note": "Fact joined to agent, queue and date dimensions at agent x day grain. Check the row count before and after each join.",
     "sql": """SELECT d.date, a.full_name AS agent, t.team_leader_name AS team_leader, q.queue_code,
       COUNT(*) AS handled, ROUND(AVG(f.handle_sec)) AS aht_sec,
       ROUND(100.0 * SUM(f.fcr) / NULLIF(SUM(f.fcr_eligible), 0), 1) AS fcr_pct
FROM fact_interaction f
JOIN dim_agent a       ON a.agent_id = f.agent_id
JOIN dim_team_leader t ON t.team_leader_id = a.team_leader_id
JOIN dim_queue q       ON q.queue_id = f.queue_id
JOIN dim_date d        ON d.date_key = f.date_key
WHERE f.handled = 1 AND d.date = '2026-05-20'
GROUP BY d.date, a.agent_id
ORDER BY handled DESC"""},
    {"id": "join-trap", "title": "The one-to-many join trap (status history)", "log": "06-Jun",
     "note": "Joining interactions to case status history multiplies rows: one interaction has several statuses. Compare the two counts.",
     "sql": """SELECT 'interactions on 20 May' AS what, COUNT(*) AS row_count
FROM fact_interaction WHERE date_key = 20260520 AND handled = 1
UNION ALL
SELECT 'after joining status history', COUNT(*)
FROM fact_interaction f JOIN fact_case_status s ON s.interaction_id = f.interaction_id
WHERE f.date_key = 20260520 AND f.handled = 1"""},
    {"id": "latest-status", "title": "Latest status per case with ROW_NUMBER()", "log": "08-Jun",
     "note": "Keep only the most recent status per case: the fix for the duplication above.",
     "sql": """WITH ranked AS (
  SELECT s.case_id, s.interaction_id, s.status, s.status_at,
         ROW_NUMBER() OVER (PARTITION BY s.case_id ORDER BY s.status_at DESC) AS rn
  FROM fact_case_status s
  JOIN fact_interaction f ON f.interaction_id = s.interaction_id
  WHERE f.date_key = 20260520)
SELECT status AS latest_status, COUNT(*) AS cases
FROM ranked WHERE rn = 1
GROUP BY status ORDER BY cases DESC"""},
    {"id": "rank-agents", "title": "Best and worst AHT agents per queue with RANK()", "log": "08-Jun",
     "note": "Window function ranking inside each queue; minimum volume avoids ranking agents on a handful of calls.",
     "sql": """WITH a AS (
  SELECT q.queue_code, ag.full_name AS agent, COUNT(*) AS handled, ROUND(AVG(f.handle_sec)) AS aht_sec
  FROM fact_interaction f
  JOIN dim_agent ag ON ag.agent_id = f.agent_id
  JOIN dim_queue q  ON q.queue_id = f.queue_id
  WHERE f.handled = 1 AND f.date_key BETWEEN 20260501 AND 20260531 AND f.agent_id <> 'UNASSIGNED'
  GROUP BY q.queue_code, ag.agent_id HAVING COUNT(*) >= 150)
SELECT *, RANK() OVER (PARTITION BY queue_code ORDER BY aht_sec) AS rank_fastest
FROM a ORDER BY queue_code, rank_fastest"""},
    {"id": "moving-average", "title": "Seven-day moving average of volume with AVG() OVER", "log": "08-Jun",
     "note": "Trend line that smooths the weekly pattern.",
     "sql": """WITH daily AS (
  SELECT d.date, SUM(c.offered) AS offered
  FROM rpt_interval_cube c JOIN dim_date d ON d.date_key = c.date_key
  WHERE c.queue_id = 'Q01' GROUP BY d.date)
SELECT date, offered,
       ROUND(AVG(offered) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS ma_7d
FROM daily ORDER BY date"""},
    {"id": "slow-query", "title": "Slow version: function on the filter column", "log": "09-Jun",
     "note": "Wrapping start_ts in a function makes the filter non-sargable: the plan shows a full SCAN of fact_interaction. Compare with the next query.",
     "sql": """SELECT queue_id, COUNT(*) AS offered, ROUND(AVG(handle_sec)) AS aht
FROM fact_interaction
WHERE strftime('%Y-%m', start_ts) = '2026-05' AND channel = 'Voice'
GROUP BY queue_id"""},
    {"id": "fast-query", "title": "Fast version: filtered CTE on an indexed date key", "log": "09-Jun",
     "note": "Same answer; the range predicate on date_key uses ix_fi_date, so the plan shows SEARCH instead of SCAN.",
     "sql": """WITH may AS (
  SELECT queue_id, handle_sec FROM fact_interaction
  WHERE date_key BETWEEN 20260501 AND 20260531 AND channel = 'Voice')
SELECT queue_id, COUNT(*) AS offered, ROUND(AVG(handle_sec)) AS aht
FROM may GROUP BY queue_id"""},
    {"id": "metric-sla", "title": "Service level and abandon rate with exclusions stated", "log": "16-Jun",
     "note": "Numerator, denominator and the short-abandon exclusion written out explicitly, as agreed with the reporting team.",
     "sql": """SELECT q.queue_code, q.sl_target,
       SUM(f.within_sl)                                              AS answered_in_threshold,
       COUNT(*) - SUM(f.short_abandon)                               AS offered_excl_short_abandons,
       ROUND(100.0 * SUM(f.within_sl) / (COUNT(*) - SUM(f.short_abandon)), 2) AS service_level_pct,
       ROUND(100.0 * (SUM(f.abandoned) - SUM(f.short_abandon)) / (COUNT(*) - SUM(f.short_abandon)), 2) AS abandon_rate_pct
FROM fact_interaction f JOIN dim_queue q ON q.queue_id = f.queue_id
WHERE f.realtime = 1 AND f.date_key BETWEEN 20260501 AND 20260531
GROUP BY q.queue_code ORDER BY service_level_pct"""},
    {"id": "fcr-lead", "title": "First contact resolution with LEAD()", "log": "16-Jun",
     "note": "Next contact by the same customer; a repeat inside seven days means the first contact did not resolve.",
     "sql": """WITH seq AS (
  SELECT f.interaction_id, f.queue_id, f.start_ts, f.handled,
         LEAD(f.start_ts) OVER (PARTITION BY f.client_id, f.customer_key ORDER BY f.start_ts) AS next_contact
  FROM fact_interaction f WHERE f.client_id = 'C01')
SELECT queue_id,
       SUM(handled) AS handled,
       SUM(CASE WHEN handled = 1 AND next_contact IS NOT NULL AND julianday(next_contact) - julianday(start_ts) <= 7 THEN 1 ELSE 0 END) AS repeats_7d,
       ROUND(100.0 - 100.0 * SUM(CASE WHEN handled = 1 AND next_contact IS NOT NULL AND julianday(next_contact) - julianday(start_ts) <= 7 THEN 1 ELSE 0 END) / SUM(handled), 2) AS fcr_pct_approx
FROM seq WHERE start_ts < '2026-05-25'
GROUP BY queue_id"""},
    {"id": "pareto", "title": "Pareto of SLA breaches by interval (Billing)", "log": "23-Jun",
     "note": "Which half-hour intervals produce most breaches, with the cumulative share.",
     "sql": """WITH iv AS (
  SELECT i.label, c.date_key, 1.0 * c.sl_num / c.sl_den AS sl
  FROM rpt_interval_cube c JOIN dim_interval i ON i.interval_idx = c.interval_idx
  WHERE c.queue_id = 'Q01' AND c.sl_den >= 5),
b AS (SELECT label, SUM(CASE WHEN sl < 0.80 THEN 1 ELSE 0 END) AS breaches FROM iv GROUP BY label)
SELECT label, breaches,
       ROUND(100.0 * SUM(breaches) OVER (ORDER BY breaches DESC ROWS UNBOUNDED PRECEDING) / SUM(breaches) OVER (), 1) AS cumulative_pct
FROM b ORDER BY breaches DESC"""},
    {"id": "staffing-gap", "title": "Staffed vs required in the morning peak (Billing)", "log": "24-Jun",
     "note": "Weekday staffing against the Erlang C requirement, before and after the 6 April roster change.",
     "sql": """SELECT CASE WHEN c.date_key < 20260406 THEN 'before 6 Apr' ELSE 'from 6 Apr' END AS period,
       i.label, ROUND(AVG(c.required_agents), 1) AS required, ROUND(AVG(c.scheduled_agents), 1) AS scheduled,
       ROUND(AVG(c.staffed_agents), 1) AS staffed,
       ROUND(100.0 * SUM(c.sl_num) / SUM(c.sl_den), 1) AS service_level_pct
FROM rpt_interval_cube c
JOIN dim_interval i ON i.interval_idx = c.interval_idx
JOIN dim_date d ON d.date_key = c.date_key
WHERE c.queue_id = 'Q01' AND d.is_weekend = 0 AND i.label BETWEEN '09:00' AND '12:30'
GROUP BY period, i.label ORDER BY i.label, period"""},
]
