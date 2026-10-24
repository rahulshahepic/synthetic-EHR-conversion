"""Bridge CLI.

  python -m bridge run --source exports/seed42 --run-db runs/r1.db [--target embedded:runs/nimbus.db | http://...]
  python -m bridge status|questions|alerts|metrics|loss|rules --run-db runs/r1.db
  python -m bridge answer <question-id> <option> [--value V] --by "user:alice" --run-db ...
  python -m bridge resume --note "answered dx questions" --run-db ...
  python -m bridge revert --scope batch|type|run [--target-id X] [--cascade] --run-db ...
  python -m bridge explain <source-key> --run-db ...
  python -m bridge mcp --run-db runs/r1.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import status as st
from .load.client import connect
from .reconcile.answers import answer
from .runs.revert import revert
from .runs.runner import DEFAULT_BATCH_SIZE, Runner
from .runs.store import RunStore


def out(obj: Any) -> None:
    print(json.dumps(obj, indent=1, default=str))


def _runner(store: RunStore, run_id: str | None) -> tuple[Runner, str]:
    run = store.run(run_id)
    return Runner(store, connect(run["target"])), run["id"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bridge")
    p.add_argument("--run-db", default="runs/bridge_run.db")
    p.add_argument("--run-id", default=None, help="defaults to the latest run in the run DB")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--source", required=True)
    r.add_argument("--target", default=None, help="default: embedded Nimbus next to the run DB")
    r.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    r.add_argument("--rules-from", help="prior run DB or exported rules JSON whose answers should be reused")
    r.add_argument("--prior-run", help="delta/cutover run: prior run DB (reuses its answers and target, detects source deletions)")
    sub.add_parser("delta")
    sub.add_parser("rules-export").add_argument("--out", required=True)
    sub.add_parser("compare").add_argument("--other-run-db", required=True, help="the earlier rehearsal's run DB")
    for name in ("status", "alerts", "rules", "events"):
        sub.add_parser(name)
    q = sub.add_parser("questions")
    q.add_argument("--all", action="store_true")
    q.add_argument("--kind")
    sub.add_parser("question").add_argument("question_id")
    a = sub.add_parser("answer")
    a.add_argument("question_id")
    a.add_argument("option")
    a.add_argument("--value")
    a.add_argument("--by", default="user")
    a.add_argument("--rationale", default="")
    ack = sub.add_parser("ack")
    ack.add_argument("alert_id")
    ack.add_argument("--note", required=True)
    ack.add_argument("--by", default="user")
    ack.add_argument("--threshold", type=float, help="new threshold for this rule and resource type")
    res = sub.add_parser("resume")
    res.add_argument("--note", default="resumed")
    res.add_argument("--by", default="user")
    pa = sub.add_parser("pause")
    pa.add_argument("--reason", default="manual")
    rp = sub.add_parser("reprocess")
    rp.add_argument("--status", action="append", default=None)
    rp.add_argument("--type")
    rv = sub.add_parser("revert")
    rv.add_argument("--scope", choices=["batch", "type", "run"], required=True)
    rv.add_argument("--target-id")
    rv.add_argument("--cascade", action="store_true")
    m = sub.add_parser("metrics")
    m.add_argument("--type")
    m.add_argument("--batch")
    sub.add_parser("loss").add_argument("--type")
    e = sub.add_parser("explain")
    e.add_argument("source_key")
    e.add_argument("--type")
    rep = sub.add_parser("report")
    rep.add_argument("--out", required=True, help="self-contained .html or .md report")
    sub.add_parser("verify")
    so = sub.add_parser("signoff")
    so.add_argument("--domain", required=True)
    so.add_argument("--by", required=True)
    so.add_argument("--note", default="")
    sub.add_parser("readiness")
    web = sub.add_parser("web")
    web.add_argument("--port", type=int, default=8710)
    web.add_argument("--host", default="127.0.0.1")
    sub.add_parser("mcp")
    args = p.parse_args(argv)

    Path(args.run_db).parent.mkdir(parents=True, exist_ok=True)
    store = RunStore(args.run_db)
    if args.cmd == "run":
        target = args.target or (RunStore(args.prior_run).run()["target"] if args.prior_run else
                                 f"embedded:{Path(args.run_db).with_name(Path(args.run_db).stem + '_nimbus.db')}")
        runner = Runner(store, connect(target))
        rules = None
        if args.rules_from:
            from .reconcile.rules_io import load_rules
            rules = load_rules(args.rules_from)
        rid = runner.start(args.source, target, args.batch_size, rules=rules, prior_run_db=args.prior_run)
        out(st.run_summary(store, rid))
    elif args.cmd == "status":
        out(st.run_summary(store, args.run_id))
    elif args.cmd == "questions":
        rid = store.run(args.run_id)["id"]
        out([{k: q[k] for k in ("id", "kind", "match_key", "blocking", "affected_count", "prompt", "status")}
             for q in store.questions(rid, None if args.all else "open", args.kind)])
    elif args.cmd == "question":
        out(store.question(args.question_id))
    elif args.cmd == "answer":
        out(answer(store, args.question_id, args.option, args.value, args.by, args.rationale))
    elif args.cmd == "alerts":
        out(store.alerts(store.run(args.run_id)["id"]))
    elif args.cmd == "ack":
        al = store.alert(args.alert_id)
        store.ack_alert(args.alert_id, args.note, args.by)
        if args.threshold is not None:
            store.set_override(al["run_id"], al["rule"], al["rtype"], args.threshold)
        out(store.alert(args.alert_id))
    elif args.cmd == "resume":
        runner, rid = _runner(store, args.run_id)
        runner.resume(rid, args.note, args.by)
        out(st.run_summary(store, rid))
    elif args.cmd == "pause":
        runner, rid = _runner(store, args.run_id)
        runner.pause(rid, args.reason)
        out(st.run_summary(store, rid))
    elif args.cmd == "reprocess":
        runner, rid = _runner(store, args.run_id)
        out({"requeued": runner.reprocess(rid, tuple(args.status or ["rejected"]), args.type)})
    elif args.cmd == "revert":
        runner, rid = _runner(store, args.run_id)
        out(revert(store, runner.client, rid, args.scope, args.target_id, args.cascade))
    elif args.cmd == "metrics":
        out(st.metrics_view(store, store.run(args.run_id)["id"], args.type, args.batch))
    elif args.cmd == "loss":
        out(store.loss_summary(store.run(args.run_id)["id"], args.type))
    elif args.cmd == "rules":
        out(store.rules(store.run(args.run_id)["id"]))
    elif args.cmd == "events":
        out(store.events(store.run(args.run_id)["id"]))
    elif args.cmd == "explain":
        out(st.explain(store, store.run(args.run_id)["id"], args.source_key, args.type))
    elif args.cmd == "delta":
        from .runs.delta import delta_summary
        out(delta_summary(store, args.run_id))
    elif args.cmd == "rules-export":
        from .reconcile.rules_io import export_rules
        data = export_rules(store, store.run(args.run_id)["id"])
        Path(args.out).write_text(json.dumps(data, indent=1))
        out({"exported": len(data["rules"]), "file": args.out})
    elif args.cmd == "compare":
        from .compare import compare, run_profile
        out(compare(run_profile(RunStore(args.other_run_db)), run_profile(store, args.run_id)))
    elif args.cmd == "report":
        from .report import report_data, render_html, render_markdown
        data = report_data(store, args.run_id)
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix.lower() not in {".html", ".md"}:
            p.error("report --out requires .html or .md")
        destination.write_text(render_html(data) if destination.suffix.lower() == ".html" else render_markdown(data), encoding="utf-8")
        out({"report": str(destination), "run_id": data["summary"]["run_id"]})
    elif args.cmd == "signoff":
        from .readiness import signoff
        out(signoff(store, store.run(args.run_id)["id"], args.domain, args.by, args.note))
    elif args.cmd == "readiness":
        from .readiness import readiness
        runner, rid = _runner(store, args.run_id)
        out(readiness(store, runner.client, rid))
    elif args.cmd == "verify":
        from .verify import verify_run
        runner, rid = _runner(store, args.run_id)
        out(verify_run(store, runner.client, rid))
    elif args.cmd == "web":
        import uvicorn
        from .web import create_app
        uvicorn.run(create_app(args.run_db), host=args.host, port=args.port)
    elif args.cmd == "mcp":
        from .mcp_server import serve
        serve(args.run_db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
