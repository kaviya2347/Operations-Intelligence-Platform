"""FastAPI service: data API for the dashboard, copilot and SQL lab, plus the static web app.

Run with:  python -m oip serve     (or: uvicorn oip.api.app:app --port 8050)
Interactive API docs: /api/docs
"""
from __future__ import annotations

import functools
import time

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from oip import artifacts, config, db
from oip.api import sql_lab
from oip.api.security import USERS, User, allowed_queues, get_user
from oip.reference import CLIENTS, HOLIDAYS, QUEUES
from oip.warehouse.metrics import CUBE_COLUMNS, TARGETS, registry_json

config.load_env_file()
app = FastAPI(title="Operations Intelligence Platform API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
              description="Contact-centre operations analytics: KPIs, root-cause analysis, forecasting, alerts and a RAG copilot.")
app.add_middleware(GZipMiddleware, minimum_size=2048)


def J(obj, status=200):
    return Response(artifacts.dumps(obj), media_type="application/json", status_code=status)


def current_user(x_oip_user: str | None = Header(default=None)) -> User:
    return get_user(x_oip_user)


# ---------------------------------------------------------------- data cache
class Store:
    def __init__(self):
        self.mtime = None
        self.cube = None
        self.agent_day = None
        self.agents = None
        self.dates = None

    def ensure(self):
        if not config.DB_PATH.exists():
            raise HTTPException(503, "Warehouse not built yet. Run: python -m oip build")
        m = config.DB_PATH.stat().st_mtime
        if self.mtime == m:
            return
        self.cube = db.read_sql(f"SELECT date_key, interval_idx, queue_id, {', '.join(CUBE_COLUMNS)} FROM rpt_interval_cube")
        self.agent_day = db.read_sql("SELECT * FROM rpt_agent_day")
        self.agents = db.read_sql("""SELECT a.agent_id, a.agent_login, a.full_name, a.site, a.team_leader_id, t.team_leader_name, a.queue_id,
                                            a.shift, a.date_of_joining, a.tenure_days_at_end, a.tenure_band
                                     FROM dim_agent a LEFT JOIN dim_team_leader t ON t.team_leader_id = a.team_leader_id
                                     WHERE a.agent_id <> 'UNASSIGNED'""")
        self.dates = db.read_sql("SELECT * FROM dim_date ORDER BY date_key")
        self.mtime = m


S = Store()


def _range(start, end):
    s = int(start.replace("-", "")) if start else 0
    e = int(end.replace("-", "")) if end else 99999999
    return s, e


def _columnar(df: pd.DataFrame) -> dict:
    out = {}
    for c in df.columns:
        v = df[c]
        if v.dtype.kind == "f":
            v = v.round(2)
            out[c] = [None if (isinstance(x, float) and np.isnan(x)) else (int(x) if float(x).is_integer() else x) for x in v.tolist()]
        else:
            out[c] = v.tolist()
    return {"n": len(df), "columns": list(df.columns), "data": out}


# ---------------------------------------------------------------- endpoints
@app.get("/api/health")
def health():
    return {"ok": True, "warehouse": config.DB_PATH.exists(), "time": time.strftime("%Y-%m-%d %H:%M:%S")}


@app.get("/api/users")
def users():
    return [u.public() for u in USERS.values()]


@app.get("/api/meta")
def meta(user: User = Depends(current_user)):
    S.ensure()
    from oip.copilot.answer import provider_status
    aq = set(allowed_queues(user))
    return J({
        "user": user.public(),
        "clients": [c for c in CLIENTS if any(q.client_id == c["client_id"] and q.queue_id in aq for q in QUEUES)],
        "queues": [{"queue_id": q.queue_id, "code": q.code, "name": q.name, "client_id": q.client_id, "channel": q.channel,
                    "sl_target": q.sl_target, "sl_threshold_sec": q.sl_threshold_sec, "aht_target_sec": q.aht_target_sec,
                    "abandon_target": q.abandon_target, "open_hour": q.open_hour, "close_hour": q.close_hour,
                    "concurrency": q.concurrency, "realtime": q.realtime} for q in QUEUES if q.queue_id in aq],
        "period": {"start": config.PERIOD_START.isoformat(), "end": config.PERIOD_END.isoformat()},
        "dates": S.dates[["date_key", "date", "weekday", "is_weekend", "is_holiday", "holiday_name", "iso_week"]].to_dict("records"),
        "metrics": registry_json(), "targets": TARGETS,
        "build": artifacts.load("build_info", {}), "llm": provider_status(),
        "intervals": [f"{i // 2:02d}:{'30' if i % 2 else '00'}" for i in range(48)],
    })


@app.get("/api/cube")
def cube(start: str | None = None, end: str | None = None, user: User = Depends(current_user)):
    S.ensure()
    s, e = _range(start, end)
    c = S.cube
    c = c[(c.date_key >= s) & (c.date_key <= e) & c.queue_id.isin(allowed_queues(user))]
    return J(_columnar(c))


@app.get("/api/agents")
def agents(start: str | None = None, end: str | None = None, user: User = Depends(current_user)):
    S.ensure()
    s, e = _range(start, end)
    aq = allowed_queues(user)
    ad = S.agent_day
    ad = ad[(ad.date_key >= s) & (ad.date_key <= e) & ad.queue_id.isin(aq)]
    dim = S.agents[S.agents.queue_id.isin(aq)].copy()
    if not user.can_see_agent_names:
        dim["full_name"] = "Agent " + dim.agent_id
        dim["team_leader_name"] = "Team " + dim.team_leader_id.fillna("")
    return J({"agent_day": _columnar(ad), "agents": dim.to_dict("records")})


@functools.lru_cache(maxsize=64)
def _rca_cached(queue_id, start, end, mtime):
    from oip.analytics.rca import run_rca
    return run_rca(queue_id, start, end)


@app.get("/api/rca")
def rca(queue: str = "Q01", start: str | None = None, end: str | None = None, user: User = Depends(current_user)):
    S.ensure()
    if queue not in allowed_queues(user):
        raise HTTPException(403, "You do not have access to this queue.")
    return J(_rca_cached(queue, start, end, S.mtime))


@app.get("/api/forecast")
def forecast(user: User = Depends(current_user)):
    f = artifacts.load("forecast", {})
    aq = set(allowed_queues(user))
    if not f:
        raise HTTPException(503, "Run python -m oip analytics first.")
    f = dict(f)
    f["results"] = [r for r in f["results"] if r["queue_id"] in aq]
    f["predictions"] = [r for r in f["predictions"] if r["queue_id"] in aq]
    f["forecast"] = [r for r in f["forecast"] if r["queue_id"] in aq]
    sp = dict(f["staffing_plan"])
    sp["intervals"] = [r for r in sp["intervals"] if r["queue_id"] in aq]
    sp["summary"] = [r for r in sp["summary"] if r["queue_id"] in aq]
    sp["worst_gaps"] = [r for r in sp["worst_gaps"] if r["queue_id"] in aq]
    f["staffing_plan"] = sp
    f["importance"] = {k: v for k, v in f["importance"].items() if any(q.code == k and q.queue_id in aq for q in QUEUES)}
    return J(f)


@app.get("/api/alerts")
def alerts(user: User = Depends(current_user)):
    a = artifacts.load("anomalies", {"incidents": [], "alerts": []})
    aq = set(allowed_queues(user))
    return J({"method": a.get("method"), "incidents": [i for i in a["incidents"] if i["queue_id"] in aq],
              "alerts": [i for i in a["alerts"] if i["queue_id"] in aq]})


@app.post("/api/alerts/{incident_id}/recommend")
def recommend(incident_id: str, user: User = Depends(current_user)):
    from oip.copilot.answer import recommend_for_incident
    a = artifacts.load("anomalies", {"incidents": []})
    inc = next((i for i in a["incidents"] if i["incident_id"] == incident_id and i["queue_id"] in allowed_queues(user)), None)
    if not inc:
        raise HTTPException(404, "Incident not found.")
    return J(recommend_for_incident(inc))


@app.get("/api/quality")
def quality(user: User = Depends(current_user)):
    if user.role not in ("Admin", "Analyst"):
        raise HTTPException(403, "Data quality is visible to Admin and Analyst roles.")
    rec = artifacts.load("reconciliation", {})
    rec = {k: v for k, v in rec.items() if k != "detail"} | {"detail": rec.get("detail", [])[:400]}
    return J({"profile": artifacts.load("profile", {}), "cleaning": artifacts.load("cleaning_log", {}), "reconciliation": rec})


@app.get("/api/eda")
def eda():
    return J(artifacts.load("eda", {}))


@app.get("/api/catalog")
def catalog(user: User = Depends(current_user)):
    c = artifacts.load("catalog", {})
    if user.role not in ("Admin", "Analyst"):
        c = dict(c)
        c["tables"] = [t for t in c.get("tables", []) if not t["name"].startswith(("stg_", "gov_"))]
    return J({**c, "metrics": registry_json(), "targets": TARGETS})


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    k: int = Field(default=5, ge=1, le=10)
    doc_types: list[str] | None = None
    queue_id: str | None = None


def live_context(queue_id: str | None, user: User) -> str | None:
    if not queue_id or queue_id not in allowed_queues(user):
        return None
    S.ensure()
    q = next(q for q in QUEUES if q.queue_id == queue_id)
    c = S.cube[(S.cube.queue_id == queue_id)]
    last = c[c.date_key >= c.date_key.max() - 6] if len(c) else c
    s = last.sum(numeric_only=True)
    sl = s.sl_num / s.sl_den if s.sl_den else None
    aht = s.handle_sec / s.handled if s.handled else None
    staff = s.staffed_agents / s.required_agents if s.required_agents else None
    rca = artifacts.load("rca", {}).get(queue_id)
    lines = [f"{q.code} ({q.name}) last 7 days: service level {sl:.1%} vs target {q.sl_target:.0%}; AHT {aht:.0f}s vs target {q.aht_target_sec}s; "
             f"staffed/required {staff:.2f}." if sl is not None else f"{q.code}: no recent data."]
    if rca and rca.get("summary"):
        lines += rca["summary"][1:4]
    return "\n".join(lines)


@app.post("/api/copilot/ask")
def ask(body: AskBody, user: User = Depends(current_user)):
    from oip.copilot.answer import answer
    return J(answer(body.question, k=body.k, doc_types=body.doc_types, live_context=live_context(body.queue_id, user)))


@app.get("/api/copilot/docs")
def copilot_docs():
    from oip.copilot.index import get_index
    idx = get_index()
    docs = {}
    for c in idx.chunks:
        d = docs.setdefault(c.doc_id, {"doc_id": c.doc_id, "title": c.title, "doc_type": c.doc_type, "chunks": 0, "sections": []})
        d["chunks"] += 1
        if c.section not in d["sections"]:
            d["sections"].append(c.section)
    return J({"docs": list(docs.values()), "index": {"chunks": len(idx.chunks), "embedder": idx.embedder.name,
                                                     "dims": int(idx.vectors.shape[1]), "chunk_words": idx.chunk_words}})


@app.get("/api/copilot/eval")
def copilot_eval():
    return J(artifacts.load("rag_eval", {}))


@app.get("/api/copilot/chunks")
def copilot_chunks():
    from oip.copilot.index import get_index
    return J([c.to_dict() for c in get_index().chunks])


class SQLBody(BaseModel):
    sql: str = Field(min_length=1, max_length=8000)


@app.get("/api/sql/saved")
def sql_saved():
    return sql_lab.SAVED


@app.post("/api/sql")
def sql(body: SQLBody, user: User = Depends(current_user)):
    if not user.can_sql:
        raise HTTPException(403, "The SQL lab is available to Admin and Analyst roles.")
    try:
        return J(sql_lab.run(body.sql))
    except sql_lab.SQLError as e:
        return J({"error": str(e)}, status=400)


@app.get("/api/settings/llm")
def llm_status():
    from oip.copilot.answer import provider_status
    return provider_status()


app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
