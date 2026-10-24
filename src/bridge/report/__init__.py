"""Standalone, escaped run reports from RunStore's public read API."""
from __future__ import annotations

from collections import Counter
from html import escape
from typing import Any

from bridge.runs.store import RunStore
from bridge.status import run_summary, metrics_view


def report_data(store: RunStore, run_id: str | None = None) -> dict[str, Any]:
    """Build a snapshot without reading run DB internals."""
    summary = run_summary(store, run_id)
    rid = summary["run_id"]
    alerts = store.alerts(rid)
    questions = store.questions(rid, status=None)
    return {
        "summary": summary,
        "metrics": metrics_view(store, rid),
        "loss": store.loss_summary(rid),
        "alerts": alerts,
        "questions": questions,
        "question_counts": dict(Counter(q["status"] for q in questions)),
    }


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _markdown_cell(value: Any) -> str:
    return _str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    return ("| " + " | ".join(headers) + " |\n"
            + "| " + " | ".join("---" for _ in headers) + " |\n"
            + "".join("| " + " | ".join(_markdown_cell(x) for x in row) + " |\n" for row in rows))


def render_markdown(data: dict[str, Any]) -> str:
    s = data["summary"]
    lines = [f"# Bridge run report: {s['run_id']}", "",
             f"Status: {_markdown_cell(s['status'])}", f"Source: {_markdown_cell(s['source'])}",
             f"Passes: {s['passes']}", f"Pause reason: {_markdown_cell(s['pause_reason'])}", "",
             "## Resource summary", ""]
    lines.append(_md_table(["Resource", "Status counts", "Mean fidelity"], [
        [kind, ", ".join(f"{status}: {count}" for status, count in sorted(info["counts"].items())),
         info["fidelity_mean"]] for kind, info in sorted(s["by_type"].items())]))
    lines += ["", "## Batch metrics", ""]
    lines.append(_md_table(["Batch", "Resource", "Status", "Attempted", "Loaded", "Rejected", "Held", "Fidelity"], [
        [m["batch"], m["rtype"], m["status"], *( (m["metrics"] or {}).get(k) for k in
         ("attempted", "loaded", "rejected", "held", "fidelity_mean"))] for m in data["metrics"]]))
    lines += ["", "## Alerts", ""]
    lines.append(_md_table(["ID", "Resource", "Rule", "Severity", "Status", "Message"], [
        [a.get(k) for k in ("id", "rtype", "rule", "severity", "status", "message")]
        for a in data["alerts"]]))
    lines += ["", "## Fidelity loss ledger", ""]
    lines.append(_md_table(["Resource", "Field", "Class", "Count", "Example"], [
        [l.get(k) for k in ("rtype", "field", "klass", "n", "example")] for l in data["loss"]]))
    lines += ["", "## Reconciliation questions", "",
              "Status counts: " + (", ".join(f"{k}: {v}" for k, v in sorted(data["question_counts"].items())) or "none"), ""]
    lines.append(_md_table(["ID", "Kind", "Key", "Status", "Blocking", "Affected", "Prompt"], [
        [q.get(k) for k in ("id", "kind", "match_key", "status", "blocking", "affected_count", "prompt")]
        for q in data["questions"]]))
    return "\n".join(lines) + "\n"


def _html_table(headers: list[str], rows: list[list[Any]]) -> str:
    heading = "".join(f"<th>{escape(_str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(_str(v))}</td>" for v in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table>"


def render_html(data: dict[str, Any]) -> str:
    """No scripts, external assets or markup supplied by source records."""
    s = data["summary"]
    sections = [
        "<h2>Resources</h2>",
        _html_table(["Resource", "Status counts", "Mean fidelity"], [
            [name, ", ".join(f"{k}: {v}" for k, v in sorted(info["counts"].items())),
             info["fidelity_mean"]] for name, info in sorted(s["by_type"].items())]),
        "<h2>Batch metrics</h2>",
        _html_table(["Batch", "Resource", "Status", "Attempted", "Loaded", "Rejected", "Held", "Fidelity"], [
            [m["batch"], m["rtype"], m["status"], *((m["metrics"] or {}).get(k) for k in
             ("attempted", "loaded", "rejected", "held", "fidelity_mean"))] for m in data["metrics"]]),
        "<h2>Alerts</h2>",
        _html_table(["ID", "Resource", "Rule", "Severity", "Status", "Message"], [
            [a.get(k) for k in ("id", "rtype", "rule", "severity", "status", "message")] for a in data["alerts"]]),
        "<h2>Fidelity loss ledger</h2>",
        _html_table(["Resource", "Field", "Class", "Count", "Example"], [
            [l.get(k) for k in ("rtype", "field", "klass", "n", "example")] for l in data["loss"]]),
        "<h2>Reconciliation questions</h2>",
        "<p>" + escape(", ".join(f"{k}: {v}" for k, v in sorted(data["question_counts"].items())) or "none") + "</p>",
        _html_table(["ID", "Kind", "Key", "Status", "Blocking", "Affected", "Prompt"], [
            [q.get(k) for k in ("id", "kind", "match_key", "status", "blocking", "affected_count", "prompt")]
            for q in data["questions"]]),
    ]
    heading = escape(_str(s["run_id"]))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Bridge run ' + heading + '</title><style>'
            'body{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.5}'
            'table{border-collapse:collapse;width:100%;margin-bottom:2rem}th,td{border:1px solid #aaa;'
            'text-align:left;padding:.4rem;overflow-wrap:anywhere}th{background:#eee}'
            'h2{margin-top:2rem}@media(max-width:700px){body{font-size:14px}table{display:block;overflow-x:auto}}'
            '</style></head><body><h1>Bridge run ' + heading + '</h1><p>Status: '
            + escape(_str(s["status"])) + ' · Passes: ' + escape(_str(s["passes"]))
            + ' · Source: ' + escape(_str(s["source"])) + '</p><p>Pause reason: '
            + escape(_str(s["pause_reason"])) + '</p>' + "".join(sections) + '</body></html>')
