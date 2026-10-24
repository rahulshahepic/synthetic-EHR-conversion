"""Read-only local dashboard over BridgeAssistant's existing query API."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from bridge.assistant import BridgeAssistant


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join("<th>" + _e(c) + "</th>" for c in headers)
    body = "".join("<tr>" + "".join("<td>" + _e(c) + "</td>" for c in row) + "</tr>" for row in rows)
    return "<div class='scroll'><table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table></div>"


def _link(path: str, title: object) -> str:
    return '<a href="' + _e(path) + '">' + _e(title) + "</a>"


def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>" + _e(title) + " · Bridge</title>"
        "<style>body{font:16px system-ui,sans-serif;max-width:1150px;margin:auto;padding:1.5rem;"
        "line-height:1.5;color:#202328;background:#fafafa}a{color:#185ca8}nav{margin-bottom:2rem}"
        "section{background:white;padding:1rem;margin:1rem 0;border:1px solid #ddd;border-radius:8px}"
        ".scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}"
        "td,th{padding:.45rem;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}"
        "th{background:#eee}input{padding:.5rem;max-width:100%}form{display:flex;gap:.5rem;flex-wrap:wrap}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#555}</style></head><body>"
        "<nav>" + _link("/", "Bridge / Runs") + "</nav><h1>" + _e(title) + "</h1>"
        + content + "</body></html>")


def create_app(run_db: str) -> FastAPI:
    """Only GET routes; no mutations, externally hosted assets or inline JavaScript."""
    assistant = BridgeAssistant(run_db)
    app = FastAPI(title="Bridge run dashboard", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def home():
        runs = assistant.list_runs()
        rows = [[_link("/runs/" + quote(run["id"], safe=""), run["id"]), run["status"],
                 run["source"], run["created_at"]] for run in runs]
        # First column contains a known-generated anchor; escape all database content in it.
        table = _table(["Run", "Status", "Source", "Created"], rows)
        for run in runs:
            path = "/runs/" + quote(run["id"], safe="")
            table = table.replace(_e(_link(path, run["id"])), _link(path, run["id"]))
        return _page("Conversion runs", "<section>" + table + "</section>")

    def _run(run_id: str):
        try:
            return assistant.run_status(run_id)
        except KeyError:
            raise HTTPException(404, "Run not found")

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(run_id: str):
        s = _run(run_id)
        base = "/runs/" + quote(run_id, safe="")
        links = " · ".join(_link(base + "/" + kind, label) for kind, label in [
            ("batches", "Batch metrics"), ("alerts", "Alerts"), ("questions", "Questions"),
            ("loss", "Fidelity loss"), ("lineage", "Record lineage")])
        summary = _table(["Resource", "Counts", "Mean fidelity"], [
            [name, ", ".join(f"{k}: {v}" for k, v in sorted(item["counts"].items())), item["fidelity_mean"]]
            for name, item in sorted(s["by_type"].items())])
        return _page("Run " + run_id, "<p>Status: <strong>" + _e(s["status"])
            + "</strong> · Open questions: " + _e(s["open_questions"]["total"])
            + " · Batches: " + _e(s["batches"]) + "</p><p>" + links
            + "</p><section><h2>Resources</h2>" + summary + "</section>")

    @app.get("/runs/{run_id}/batches", response_class=HTMLResponse)
    def batches(run_id: str):
        _run(run_id)
        values = assistant.get_metrics(run_id)
        return _page("Batch metrics", "<section>" + _table(
            ["Batch", "Resource", "Status", "Attempted", "Loaded", "Rejected", "Held", "Fidelity"],
            [[v["batch"], v["rtype"], v["status"], *((v.get("metrics") or {}).get(k) for k in
               ("attempted", "loaded", "rejected", "held", "fidelity_mean"))] for v in values]) + "</section>")

    @app.get("/runs/{run_id}/alerts", response_class=HTMLResponse)
    def alerts(run_id: str):
        _run(run_id)
        return _page("Alerts", "<section>" + _table(
            ["Rule", "Resource", "Severity", "Status", "Message"],
            [[a.get(k) for k in ("rule", "rtype", "severity", "status", "message")]
             for a in assistant.list_alerts(run_id, status=None)]) + "</section>")

    @app.get("/runs/{run_id}/questions", response_class=HTMLResponse)
    def questions(run_id: str):
        _run(run_id)
        result = assistant.list_questions(run_id, status="", limit=1000)
        return _page("Reconciliation questions", "<p>Total: " + _e(result["total"]) + "</p><section>"
            + _table(["Kind", "Blocking", "Status", "Affected", "Prompt"],
                     [[q.get(k) for k in ("kind", "blocking", "status", "records_affected", "prompt")]
                      for q in result["questions"]]) + "</section>")

    @app.get("/runs/{run_id}/loss", response_class=HTMLResponse)
    def loss(run_id: str):
        _run(run_id)
        return _page("Fidelity loss", "<section>" + _table(
            ["Resource", "Field", "Class", "Count", "Example"],
            [[row.get(k) for k in ("rtype", "field", "klass", "n", "example")]
             for row in assistant.loss_report(run_id, limit=1000)]) + "</section>")

    @app.get("/runs/{run_id}/lineage", response_class=HTMLResponse)
    def lineage(run_id: str, source_key: str = "", resource_type: str = ""):
        _run(run_id)
        base = "/runs/" + quote(run_id, safe="") + "/lineage"
        form = ('<form action="' + _e(base) + '" method="get">'
                '<label>Source key <input name="source_key" required value="' + _e(source_key) + '"></label>'
                '<label>Resource type <input name="resource_type" value="' + _e(resource_type) + '"></label>'
                '<button type="submit">Find record</button></form>')
        rows = assistant.explain_record(source_key, resource_type or None, run_id) if source_key else []
        detail = _table(["Resource", "Source key", "Status", "Batch", "Nimbus ID", "Lineage", "Fidelity"],
                        [[r.get(k) for k in ("rtype", "source_key", "status", "batch", "nimbus_id", "lineage", "fidelity")]
                         for r in rows])
        return _page("Record lineage", "<section>" + form + detail + "</section>")

    return app
