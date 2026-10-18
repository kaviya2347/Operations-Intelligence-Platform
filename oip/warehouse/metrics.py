"""Metric registry: one definition per KPI, used by every engine.

Each metric is a ratio of sums over the interval cube (so any slice of the
dashboard aggregates correctly) and has an equivalent SQL definition over the
interaction fact table. tests/test_metrics.py checks the two agree, the same way
DAX measures were validated against SQL during the internship.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from oip import config


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    unit: str                    # pct | sec | count | ratio
    direction: str               # up | down | neutral (which way is good)
    num: tuple                   # ((cube_column, sign), ...)
    den: tuple | None
    definition: str
    numerator: str
    denominator: str
    exclusions: str
    sql: str | None = None       # SQL over fact_interaction f (parity source); None if WFM-based
    target_key: str | None = None
    group: str = "Service"
    business_question: str = ""
    tags: tuple = field(default_factory=tuple)


METRICS: list[Metric] = [
    Metric("offered", "Offered", "count", "neutral", (("offered", 1),), None,
           "All contacts that entered a queue (calls, chats, emails, back-office cases).", "Count of contacts", "-",
           "None", "COUNT(*)", group="Volume", business_question="How much work arrived?"),
    Metric("handled", "Handled", "count", "neutral", (("handled", 1),), None,
           "Contacts answered by an agent (or responded to, for email and back office).", "Count of handled contacts", "-",
           "Abandoned contacts", "SUM(f.handled)", group="Volume", business_question="How much work did we do?"),
    Metric("sl", "Service level", "pct", "up", (("sl_num", 1),), (("sl_den", 1),),
           "Share of contacts answered within the queue's threshold (e.g. 80% in 20 s for Billing; first response within 4 business hours for email).",
           "Contacts handled within the queue threshold", "Offered contacts minus short abandons",
           f"Short abandons (abandoned within {config.SHORT_ABANDON_SEC} s) are excluded from the denominator",
           "SUM(f.within_sl) * 1.0 / SUM(f.sl_eligible)", target_key="sl_target", group="Service",
           business_question="Are customers reached as fast as the contract says?"),
    Metric("abandon_rate", "Abandon rate", "pct", "down", (("abandoned", 1), ("short_abandoned", -1)),
           (("rt_offered", 1), ("short_abandoned", -1)),
           "Share of real-time contacts (voice and chat) where the customer left before an agent answered.",
           "Abandoned contacts minus short abandons", "Offered real-time contacts minus short abandons",
           f"Short abandons (<= {config.SHORT_ABANDON_SEC} s); email and back office have no abandons",
           "(SUM(f.abandoned) - SUM(f.short_abandon)) * 1.0 / (SUM(f.realtime) - SUM(f.short_abandon))", target_key="abandon_target",
           group="Service", business_question="How many customers gave up waiting?"),
    Metric("asa", "Average speed of answer", "sec", "down", (("asa_num", 1),), (("asa_den", 1),),
           "Average wait before an agent answered, for answered voice and chat contacts.", "Total wait of answered real-time contacts",
           "Answered real-time contacts", "Abandoned contacts; email and back office",
           "SUM(CASE WHEN f.handled = 1 AND f.realtime = 1 THEN f.wait_sec END) / SUM(CASE WHEN f.handled = 1 AND f.realtime = 1 THEN 1 END)",
           group="Service", business_question="How long do answered customers wait?"),
    Metric("aht", "Average handle time", "sec", "down", (("handle_sec", 1),), (("handled", 1),),
           "Talk + hold + after-call work per handled contact.", "Talk + hold + ACW seconds", "Handled contacts",
           "Abandoned contacts; unclosed sessions are capped at queue P99 (rule R08)", "SUM(f.handle_sec) / SUM(f.handled)",
           target_key="aht_target_sec", group="Efficiency", business_question="How much agent time does a contact take?"),
    Metric("acw", "Average after-call work", "sec", "down", (("acw_sec", 1),), (("handled", 1),),
           "Wrap-up time after the customer leaves, per handled contact.", "ACW seconds", "Handled contacts", "Abandoned contacts",
           "SUM(f.acw_sec) / SUM(f.handled)", group="Efficiency", business_question="How long does wrap-up take?"),
    Metric("hold", "Average hold", "sec", "down", (("hold_sec", 1),), (("handled", 1),),
           "Time customers are placed on hold, per handled contact.", "Hold seconds", "Handled contacts", "Abandoned contacts",
           "SUM(f.hold_sec) / SUM(f.handled)", group="Efficiency", business_question="Are agents searching for answers mid-call?"),
    Metric("fcr", "First contact resolution", "pct", "up", (("fcr_num", 1),), (("fcr_den", 1),),
           f"Handled contacts where the same customer did not contact the same client again within {config.FCR_WINDOW_DAYS} days.",
           f"Handled contacts with no repeat contact within {config.FCR_WINDOW_DAYS} days", f"Handled contacts that started at least {config.FCR_WINDOW_DAYS} days before the period end",
           f"Contacts in the last {config.FCR_WINDOW_DAYS} days of the period (repeat window not yet complete)",
           "SUM(f.fcr) * 1.0 / SUM(f.fcr_eligible)", target_key="fcr_target", group="Quality",
           business_question="Did we solve it the first time?"),
    Metric("csat", "CSAT (top-2 box)", "pct", "up", (("csat_top2", 1),), (("csat_resp", 1),),
           f"Share of survey responses scoring {config.CSAT_TOP_BOX} or 5 on a 1-5 scale.", "Responses scoring 4 or 5", "Valid survey responses",
           "Invalid scores outside 1-5 (rule R12); non-responders", None, target_key="csat_target", group="Quality",
           business_question="Are customers satisfied?"),
    Metric("transfer_rate", "Transfer rate", "pct", "down", (("transferred", 1),), (("handled", 1),),
           "Share of handled contacts transferred to another queue or level.", "Transferred contacts", "Handled contacts", "None",
           "SUM(f.transferred) * 1.0 / SUM(f.handled)", group="Quality", business_question="How often does the first agent fail to finish?"),
    Metric("occupancy", "Occupancy", "pct", "neutral", (("handle_sec", 1),), (("capacity_sec", 1),),
           "Share of staffed capacity spent handling contacts (chat capacity counts two concurrent sessions per agent).", "Handle seconds",
           "Staffed agents x 1,800 s per interval x concurrency", "Intervals with no staff",
           None, target_key="occupancy_target", group="Workforce", business_question="Are agents over- or under-utilised?"),
    Metric("shrinkage", "Shrinkage", "pct", "down", (("scheduled_sec", 1), ("staffed_sec", -1)), (("scheduled_sec", 1),),
           "Share of scheduled time lost to leave, absence, breaks and training.", "Scheduled minus staffed agent-seconds",
           "Scheduled agent-seconds", "None", None, target_key="shrinkage_target", group="Workforce",
           business_question="How much planned capacity actually showed up?"),
    Metric("staffing_ratio", "Staffed vs required", "pct", "up", (("staffed_agents", 1),), (("required_agents", 1),),
           "Staffed agent-intervals as a share of what the forecast required to meet service level.", "Staffed agent-intervals",
           "Required agent-intervals (Erlang C on forecast)", "None", None, group="Workforce",
           business_question="Did we have enough people when the work arrived?"),
    Metric("wape", "Forecast error (WAPE)", "pct", "down", (("abs_fc_err", 1),), (("offered", 1),),
           "Weighted absolute percentage error of the WFM interval forecast.", "Sum of |actual - forecast| by interval", "Actual offered",
           "None", None, group="Workforce", business_question="How good was the volume forecast?"),
    Metric("forecast_volume", "Forecast volume", "count", "neutral", (("forecast_volume", 1),), None,
           "WFM forecast of offered contacts.", "Forecast contacts", "-", "None", None, group="Workforce"),
]
METRIC_BY_ID = {m.id: m for m in METRICS}

TARGETS = {"fcr_target": 0.80, "csat_target": 0.85, "occupancy_target": 0.85, "shrinkage_target": config.PLANNED_SHRINKAGE}

CUBE_COLUMNS = ["offered", "rt_offered", "handled", "abandoned", "short_abandoned", "sl_num", "sl_den", "asa_num", "asa_den",
                "talk_sec", "hold_sec", "acw_sec", "handle_sec", "transferred", "fcr_num", "fcr_den", "csat_resp", "csat_top2",
                "csat_sum", "forecast_volume", "fc_aht_x_vol", "required_agents", "scheduled_agents", "staffed_agents",
                "staffed_sec", "scheduled_sec", "capacity_sec", "abs_fc_err"]


def registry_json() -> list[dict]:
    out = []
    for m in METRICS:
        d = asdict(m)
        d["num"] = [list(x) for x in m.num]
        d["den"] = [list(x) for x in m.den] if m.den else None
        out.append(d)
    return out


def dax_measures(table: str = "rpt_interval_cube") -> str:
    """Generate Power BI measures from the registry (same ratio-of-sums logic)."""
    def expr(terms):
        return " ".join(("+ " if s > 0 else "- ") + f"SUM({table}[{c}])" for c, s in terms).lstrip("+ ").strip()
    lines = ["// Generated from oip/warehouse/metrics.py. Do not edit by hand.", ""]
    for m in METRICS:
        num = expr(m.num)
        body = f"DIVIDE({num}, {expr(m.den)})" if m.den else num
        lines.append(f"// {m.definition}\n// Exclusions: {m.exclusions}")
        lines.append(f"[{m.label}] = {body}\n")
    lines += ["// Time intelligence (requires dim_date marked as date table)",
              "[Service level MTD] = CALCULATE([Service level], DATESMTD(dim_date[date]))",
              "[Service level PM] = CALCULATE([Service level], DATEADD(dim_date[date], -1, MONTH))",
              "[Offered MTD] = CALCULATE([Offered], DATESMTD(dim_date[date]))",
              "[Offered PM] = CALCULATE([Offered], DATEADD(dim_date[date], -1, MONTH))",
              "[Average handle time PM] = CALCULATE([Average handle time], DATEADD(dim_date[date], -1, MONTH))", ""]
    return "\n".join(lines)
