-- Operations Intelligence Platform: warehouse schema (star schema, SQLite dialect)
-- Grain notes are on each table. Facts join to dimensions on surrogate or natural keys.

DROP TABLE IF EXISTS dim_date;
CREATE TABLE dim_date (
  date_key      INTEGER PRIMARY KEY,          -- YYYYMMDD
  date          TEXT NOT NULL,
  day_of_month  INTEGER, weekday_num INTEGER, weekday TEXT, iso_week INTEGER,
  month_num     INTEGER, month_name TEXT, is_weekend INTEGER, is_holiday INTEGER, holiday_name TEXT
);

DROP TABLE IF EXISTS dim_interval;
CREATE TABLE dim_interval (
  interval_idx  INTEGER PRIMARY KEY,          -- 0..47, 30-minute buckets
  label         TEXT NOT NULL,                -- HH:MM
  hour          INTEGER, shift_window TEXT
);

DROP TABLE IF EXISTS dim_client;
CREATE TABLE dim_client (
  client_id TEXT PRIMARY KEY, client_code TEXT, client_name TEXT, industry TEXT, contract_tier TEXT
);

DROP TABLE IF EXISTS dim_queue;
CREATE TABLE dim_queue (
  queue_id TEXT PRIMARY KEY, queue_code TEXT, queue_name TEXT, client_id TEXT REFERENCES dim_client(client_id),
  channel TEXT, open_hour INTEGER, close_hour INTEGER, sl_threshold_sec INTEGER, sl_target REAL,
  aht_target_sec INTEGER, abandon_target REAL, concurrency INTEGER
);

DROP TABLE IF EXISTS dim_team_leader;
CREATE TABLE dim_team_leader (team_leader_id TEXT PRIMARY KEY, team_leader_name TEXT, queue_code TEXT, shift TEXT);

DROP TABLE IF EXISTS dim_agent;
CREATE TABLE dim_agent (
  agent_id TEXT PRIMARY KEY, agent_login TEXT, full_name TEXT, site TEXT,
  team_leader_id TEXT REFERENCES dim_team_leader(team_leader_id), queue_id TEXT REFERENCES dim_queue(queue_id),
  shift TEXT, date_of_joining TEXT, tenure_days_at_end INTEGER, tenure_band TEXT
);

DROP TABLE IF EXISTS dim_customer;
CREATE TABLE dim_customer (
  customer_key TEXT PRIMARY KEY, client_code TEXT, name_masked TEXT, phone_masked TEXT, email_masked TEXT, city TEXT
);

DROP TABLE IF EXISTS fact_interaction;
CREATE TABLE fact_interaction (               -- grain: one row per offered contact
  interaction_id INTEGER PRIMARY KEY,
  source_system TEXT, source_ref TEXT, channel TEXT,
  queue_id TEXT REFERENCES dim_queue(queue_id), client_id TEXT REFERENCES dim_client(client_id),
  agent_id TEXT, customer_key TEXT, case_id TEXT,
  start_ts TEXT, answer_ts TEXT, end_ts TEXT,
  date_key INTEGER REFERENCES dim_date(date_key), interval_idx INTEGER REFERENCES dim_interval(interval_idx),
  hour INTEGER, weekday TEXT, shift_window TEXT,
  handled INTEGER, abandoned INTEGER, short_abandon INTEGER, realtime INTEGER,
  wait_sec REAL, talk_sec REAL, hold_sec REAL, acw_sec REAL, handle_sec REAL,
  sl_threshold_sec INTEGER, within_sl INTEGER, sl_eligible INTEGER, transferred INTEGER,
  reason TEXT, resolution TEXT, latest_status TEXT,
  next_contact_ts TEXT, repeat_7d INTEGER, fcr_eligible INTEGER, fcr INTEGER,
  disposition_imputed INTEGER, hold_imputed INTEGER, wait_corrected INTEGER, agent_missing INTEGER,
  unclosed_session INTEGER, long_handle_reviewed INTEGER, talk_sec_raw REAL
);

DROP TABLE IF EXISTS fact_case_status;
CREATE TABLE fact_case_status (               -- grain: one row per case status change (one-to-many with interaction)
  history_id TEXT PRIMARY KEY, case_id TEXT, interaction_id INTEGER, status TEXT, status_at TEXT
);

DROP TABLE IF EXISTS fact_csat;
CREATE TABLE fact_csat (survey_id TEXT PRIMARY KEY, interaction_id INTEGER, score INTEGER, responded_at TEXT);

DROP TABLE IF EXISTS fact_qa;
CREATE TABLE fact_qa (
  audit_id TEXT PRIMARY KEY, interaction_id INTEGER, agent_id TEXT, audit_date TEXT,
  greeting REAL, verification REAL, resolution REAL, empathy REAL, compliance REAL, total_score REAL, fatal_error INTEGER
);

DROP TABLE IF EXISTS fact_wfm_interval;
CREATE TABLE fact_wfm_interval (              -- grain: queue x date x 30-minute interval
  date_key INTEGER, interval_idx INTEGER, queue_id TEXT,
  forecast_volume REAL, forecast_aht_sec REAL, required_agents INTEGER, scheduled_agents INTEGER, staffed_agents INTEGER,
  PRIMARY KEY (date_key, interval_idx, queue_id)
);

DROP TABLE IF EXISTS fact_agent_session;
CREATE TABLE fact_agent_session (
  session_id TEXT PRIMARY KEY, agent_id TEXT, date_key INTEGER, login_ts TEXT, logout_ts TEXT,
  logged_in_sec REAL, aux_sec REAL, unclosed INTEGER
);
