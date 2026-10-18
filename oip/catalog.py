"""Data catalog: tables, grain, row counts, columns and PII classification, read from the live database."""
from __future__ import annotations

from oip import db

DESCRIPTIONS = {
    "fact_interaction": ("One row per offered contact (all channels)", "Fact"),
    "fact_case_status": ("One row per CRM case status change; many per interaction", "Fact"),
    "fact_csat": ("One row per valid survey response", "Fact"),
    "fact_qa": ("One row per quality audit", "Fact"),
    "fact_wfm_interval": ("Queue x date x 30-min interval: forecast, required, scheduled, staffed", "Fact"),
    "fact_agent_session": ("One row per agent per worked day: login, logout, aux", "Fact"),
    "dim_date": ("Calendar with weekday, ISO week, month and holidays", "Dimension"),
    "dim_interval": ("48 half-hour intervals with shift window", "Dimension"),
    "dim_client": ("Clients served by the delivery centre", "Dimension"),
    "dim_queue": ("Queues with channel, hours and contractual targets", "Dimension"),
    "dim_agent": ("Agents with site, team leader, shift and tenure", "Dimension"),
    "dim_team_leader": ("Team leaders by queue and shift", "Dimension"),
    "dim_customer": ("Customers, masked (no clear PII)", "Dimension"),
    "rpt_interval_cube": ("Reporting cube: queue x date x interval with every metric numerator and denominator", "Reporting"),
    "rpt_agent_day": ("Agent x date x queue performance", "Reporting"),
    "rpt_queue_day": ("Queue x date KPIs (view)", "Reporting"),
    "gov_pii_register": ("Sensitive columns and the masking applied", "Governance"),
    "gov_load_log": ("Every ingestion batch with row counts and checksums", "Governance"),
    "gov_cleaning_log": ("Cleaning rules and rows affected by each", "Governance"),
}
SENSITIVE = {"full_name": "Employee name (internal)", "name_masked": "Masked customer name", "phone_masked": "Masked phone",
             "email_masked": "Masked email", "customer_key": "Pseudonymous key"}


def build_catalog() -> dict:
    objs = db.read_sql("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = []
    for r in objs.itertuples():
        if r.name.startswith("_"):
            continue
        cols = db.read_sql(f"PRAGMA table_info('{r.name}')")
        n = int(db.read_sql(f"SELECT COUNT(*) n FROM {r.name}").n.iloc[0])
        layer = "Staging" if r.name.startswith("stg_") else DESCRIPTIONS.get(r.name, ("", "Other"))[1]
        tables.append({"name": r.name, "type": r.type, "layer": layer, "rows": n,
                       "description": DESCRIPTIONS.get(r.name, ("Landing copy of a source extract (PII masked)" if r.name.startswith("stg_") else "", ""))[0],
                       "columns": [{"name": c.name, "type": c.type or "TEXT", "pk": bool(c.pk), "sensitivity": SENSITIVE.get(c.name)}
                                   for c in cols.itertuples()]})
    rel = [
        ("fact_interaction", "queue_id", "dim_queue", "queue_id", "many-to-one"),
        ("fact_interaction", "client_id", "dim_client", "client_id", "many-to-one"),
        ("fact_interaction", "agent_id", "dim_agent", "agent_id", "many-to-one"),
        ("fact_interaction", "date_key", "dim_date", "date_key", "many-to-one"),
        ("fact_interaction", "interval_idx", "dim_interval", "interval_idx", "many-to-one"),
        ("fact_interaction", "customer_key", "dim_customer", "customer_key", "many-to-one"),
        ("fact_case_status", "interaction_id", "fact_interaction", "interaction_id", "many-to-one (one interaction, many statuses)"),
        ("fact_csat", "interaction_id", "fact_interaction", "interaction_id", "zero-or-one per interaction"),
        ("fact_qa", "interaction_id", "fact_interaction", "interaction_id", "zero-or-one per interaction"),
        ("fact_wfm_interval", "queue_id + date_key + interval_idx", "rpt_interval_cube", "same grain", "one-to-one"),
        ("dim_agent", "team_leader_id", "dim_team_leader", "team_leader_id", "many-to-one"),
        ("dim_queue", "client_id", "dim_client", "client_id", "many-to-one"),
    ]
    pii = db.read_sql("SELECT * FROM gov_pii_register").to_dict("records")
    return {"tables": tables, "relationships": [dict(zip(["from_table", "from_column", "to_table", "to_column", "cardinality"], r)) for r in rel],
            "pii_register": pii}
