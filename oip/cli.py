"""Command line: python -m oip <command>

  build           generate sources -> ingest -> profile -> clean -> reconcile -> warehouse -> analytics -> copilot index
  generate        regenerate synthetic source extracts only
  analytics       rerun EDA, RCA, forecasting and anomaly detection on the current warehouse
  index           rebuild the copilot knowledge-base index (and run the retrieval evaluation)
  serve           start the API and dashboard (default http://127.0.0.1:8050)
  ask "question"  ask the operations copilot from the terminal
  status          show the last build, row counts, checks and artifacts
  export-powerbi  write star-schema CSVs, DAX measures and model notes to ./powerbi  (--with-facts adds fact_interaction)
  export-static   write web/static/snapshot.js so the dashboard runs without the API
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from oip import artifacts, config


def _hdr(t):
    print(f"\n== {t}", flush=True)


def cmd_generate(args):
    from oip.generate.synth import generate
    config.ensure_dirs()
    _hdr("Generate synthetic source systems")
    generate(seed=args.seed)


def cmd_pipeline(args):
    from oip import db
    from oip.pipeline.clean import run_clean
    from oip.pipeline.ingest import ingest
    from oip.pipeline.profile import run_profile
    from oip.pipeline.reconcile import reconcile
    from oip.warehouse.build import build_warehouse
    from oip.catalog import build_catalog
    from oip.warehouse.metrics import registry_json, TARGETS
    db.reset_engine()
    if config.DB_PATH.exists():
        for suffix in ("", "-wal", "-shm"):
            p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
            if p.exists():
                p.unlink()
    _hdr("Ingest to staging (PII masked)")
    ing = ingest()
    _hdr("Profile staging")
    prof = run_profile()
    artifacts.save("profile", prof)
    _hdr("Clean")
    clean, log = run_clean()
    _hdr("Reconcile against source reports")
    rec = reconcile(clean)
    artifacts.save("reconciliation", rec)
    _hdr("Build warehouse")
    counts = build_warehouse(clean, log)
    artifacts.save("cleaning_log", {"steps": log.steps, "ingest": ing, "warehouse_counts": counts,
                                    "outliers": _outlier_summary(clean)})
    artifacts.save("catalog", build_catalog())
    artifacts.save("metrics", {"metrics": registry_json(), "targets": TARGETS})


def _outlier_summary(clean):
    import numpy as np
    v = clean[(clean.channel == "Voice") & clean.handled]
    bins = np.arange(0, 3601, 120)
    before, _ = np.histogram(v.talk_sec_raw.fillna(0) + v.hold_sec + v.acw_sec, bins=np.append(bins, 1e9))
    after, _ = np.histogram(v.handle_sec, bins=np.append(bins, 1e9))
    return {"bins": [int(b) for b in bins], "before": before.tolist(), "after": after.tolist(),
            "max_before": float((v.talk_sec_raw + v.hold_sec + v.acw_sec).max()), "max_after": float(v.handle_sec.max()),
            "capped": int(clean.unclosed_session.sum()), "kept_long": int(clean.long_handle_reviewed.sum())}


def cmd_analytics(args):
    from oip.analytics.anomaly import run_anomaly
    from oip.analytics.eda import run_eda
    from oip.analytics.forecast import run_forecast
    from oip.analytics.rca import run_rca
    from oip.reference import QUEUES
    _hdr("Exploratory analysis")
    artifacts.save("eda", run_eda())
    _hdr("Root-cause analysis (all real-time queues)")
    rca = {q.queue_id: run_rca(q.queue_id) for q in QUEUES if q.realtime}
    for k, v in rca.items():
        print(f"  [rca] {v['queue_code']}: {v['totals']['breaches']} breach intervals; " + (v["summary"][3] if len(v["summary"]) > 3 else ""), flush=True)
    artifacts.save("rca", rca)
    _hdr("Forecasting")
    artifacts.save("forecast", run_forecast())
    _hdr("Anomaly detection")
    artifacts.save("anomalies", run_anomaly(rca=rca))


def cmd_index(args):
    from oip.copilot.index import build_index
    from oip.copilot.evaluate import run_eval
    _hdr("Copilot: index knowledge base")
    build_index()
    _hdr("Copilot: retrieval evaluation")
    artifacts.save("rag_eval", run_eval())


def cmd_build(args):
    t0 = time.time()
    cmd_generate(args)
    cmd_pipeline(args)
    cmd_analytics(args)
    cmd_index(args)
    info = {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - t0, 1), "seed": args.seed,
            "period": [config.PERIOD_START.isoformat(), config.PERIOD_END.isoformat()]}
    artifacts.save("build_info", info)
    print(f"\nBuild complete in {info['seconds']}s. Start the app with:  python -m oip serve\n", flush=True)


def cmd_serve(args):
    import uvicorn
    print(f"\n  Operations Intelligence Platform: http://{args.host}:{args.port}\n", flush=True)
    uvicorn.run("oip.api.app:app", host=args.host, port=args.port, log_level="warning")


def cmd_ask(args):
    from oip.copilot.answer import answer
    res = answer(" ".join(args.question))
    print("\n" + res["answer"] + "\n")
    for c in res["citations"]:
        print(f"  [{c['n']}] {c['doc_id']} · {c['title']} § {c['section']}")
    print(f"\n  ({res['provider']}, {res['latency_ms']} ms)\n")


def cmd_export_powerbi(args):
    from oip.exports import export_powerbi
    export_powerbi(with_facts=args.with_facts)


def cmd_status(args):
    from oip import db
    info = artifacts.load("build_info", {})
    print(f"\n  Last build: {info.get('built_at', 'never')} ({info.get('seconds', '?')} s, seed {info.get('seed', '?')})")
    if not config.DB_PATH.exists():
        print("  Warehouse: not built. Run: python -m oip build\n")
        return
    for t in ("fact_interaction", "fact_case_status", "fact_csat", "fact_qa", "fact_wfm_interval", "rpt_interval_cube", "rpt_agent_day"):
        print(f"  {t:<20} {int(db.read_sql(f'SELECT COUNT(*) n FROM {t}').n[0]):>10,} rows")
    rec = artifacts.load("reconciliation", {}).get("current", {})
    ev = artifacts.load("rag_eval", {}).get("final", {})
    an = artifacts.load("anomalies", {})
    print(f"  Reconciliation       {rec.get('matched')}/{rec.get('rows')} queue-days match source")
    print(f"  Copilot retrieval    hit@3 {ev.get('hit_at_3')}, MRR {ev.get('mrr')}, citation accuracy {ev.get('citation_accuracy')}")
    print(f"  Open incidents       {len(an.get('incidents', []))}")
    print(f"  Artifacts            {', '.join(sorted(p.stem for p in config.ARTIFACTS_DIR.glob('*.json')))}\n")


def cmd_export_static(args):
    from oip.exports import export_static
    export_static()


def main(argv=None):
    config.load_env_file()
    p = argparse.ArgumentParser(prog="oip", description="Operations Intelligence Platform")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--seed", type=int, default=config.SEED); b.set_defaults(fn=cmd_build)
    g = sub.add_parser("generate"); g.add_argument("--seed", type=int, default=config.SEED); g.set_defaults(fn=cmd_generate)
    sub.add_parser("pipeline").set_defaults(fn=cmd_pipeline)
    sub.add_parser("analytics").set_defaults(fn=cmd_analytics)
    sub.add_parser("index").set_defaults(fn=cmd_index)
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8050); s.set_defaults(fn=cmd_serve)
    a = sub.add_parser("ask"); a.add_argument("question", nargs="+"); a.set_defaults(fn=cmd_ask)
    e = sub.add_parser("export-powerbi"); e.add_argument("--with-facts", action="store_true"); e.set_defaults(fn=cmd_export_powerbi)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("export-static").set_defaults(fn=cmd_export_static)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
