"""Build the static demo site (GitHub Pages) from a `python -m testbed.demo` output directory.

    python tools/build_site.py demo_out site

Writes site/index.html (headline numbers, fidelity chart, the narrated run) and copies the full run report.
Self-contained: no external assets.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from bridge.runs.store import RunStore
from bridge.status import run_summary

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--accent:#2f6f5e;--good:#2f7d32;--bad:#b3261e;--bar:#7fb5a5}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--fg:#ecece8;--muted:#a3a39c;--line:#33332f;--accent:#7fc4ae;--good:#81c784;--bad:#f28b82;--bar:#4f8f7e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
header h1{margin:0 0 4px;font-size:28px}header p{margin:0;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .v{font-size:26px;font-weight:650}.card .k{color:var(--muted);font-size:13px}
.good{color:var(--good)}.bad{color:var(--bad)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:16px 0}
h2{font-size:20px;margin:6px 0 10px}h3{font-size:16px}
table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;white-space:nowrap}th{color:var(--muted);font-weight:600}
.bars .row{display:grid;grid-template-columns:150px 1fr 52px;gap:8px;align-items:center;font-size:14px;margin:4px 0}
.bars .track{background:var(--line);border-radius:6px;height:12px;overflow:hidden}.bars .fill{background:var(--bar);height:100%}
code{background:var(--line);padding:1px 5px;border-radius:5px;font-size:13px}
a{color:var(--accent)}ul{padding-left:20px}footer{color:var(--muted);font-size:13px;margin-top:24px}
"""


def inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"_([^_]+)_$", r"<em>\1</em>", t)
    return t


def markdown(md: str) -> str:
    """Minimal Markdown for the transcript: headings, paragraphs, bullet lists, tables, bold/italic/code."""
    out, lines, i = [], md.splitlines(), 0
    section_open = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            i += 1
            continue  # page has its own title
        if line.startswith("## "):
            if section_open:
                out.append("</section>")
            out.append(f"<section><h2>{inline(line[3:])}</h2>")
            section_open = True
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table>")
            continue
        elif line.lstrip().startswith("- "):
            out.append("<ul>")
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                out.append(f"<li>{inline(lines[i].lstrip()[2:])}</li>")
                i += 1
            out.append("</ul>")
            continue
        elif line.strip():
            out.append(f"<p>{inline(line.strip())}</p>")
        i += 1
    if section_open:
        out.append("</section>")
    return "\n".join(out)


def headline(demo: Path) -> tuple[list[tuple[str, str, str]], list[tuple[str, float]]]:
    store = RunStore(str(demo / "rehearsal1.db"))
    s = run_summary(store)
    rid = s["run_id"]
    loaded = sum(v["counts"].get("loaded", 0) for v in s["by_type"].values())
    patients = s["by_type"].get("Patient", {}).get("counts", {}).get("loaded", 0)
    answered = len(store.questions(rid, "answered"))
    pauses = sum(1 for e in store.events(rid, 100000) if e["kind"] == "status" and (e["detail"] or {}).get("status") == "paused")
    verif = next((e["detail"] for e in store.events(rid, 100000) if e["kind"] == "verification"), {})
    ready = next((e["detail"] for e in store.events(rid, 100000) if e["kind"] == "readiness"), {})
    fids = [(t, v["fidelity_mean"]) for t, v in s["by_type"].items() if v["fidelity_mean"] is not None]
    weighted = sum(v["counts"].get("loaded", 0) * (v["fidelity_mean"] or 0) for v in s["by_type"].values()) / max(loaded, 1)
    cards = [
        (f"{patients:,}", "patients converted", ""),
        (f"{loaded:,}", "records loaded into Nimbus", ""),
        (f"{weighted:.3f}", "mean fidelity (1.0 = lossless)", ""),
        (str(answered), "human decisions (grouped)", ""),
        (str(pauses), "safety pauses", ""),
        ("OK" if verif.get("ok") else "FAILED", "end-of-run verification", "good" if verif.get("ok") else "bad"),
        (ready.get("decision", "n/a"), "go-live readiness", "good" if ready.get("decision") == "GO" else "bad"),
    ]
    return cards, sorted(fids, key=lambda x: x[1])


def build(demo: Path, site: Path) -> None:
    site.mkdir(parents=True, exist_ok=True)
    cards, fids = headline(demo)
    transcript = (demo / "DEMO_TRANSCRIPT.md").read_text()
    report = demo / "rehearsal1_report.html"
    if report.exists():
        shutil.copy(report, site / "report.html")
    bars = "".join(
        f'<div class="row"><span>{html.escape(t)}</span><div class="track"><div class="fill" style="width:{f * 100:.1f}%"></div></div>'
        f"<span>{f:.3f}</span></div>" for t, f in fids)
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bridge conversion demo</title><style>{CSS}</style></head>
<body><main>
<header><h1>Bridge: legacy EHR → Nimbus conversion</h1>
<p>Synthetic data only. Halcyon (messy legacy export) converted into Nimbus with a simulated analyst answering Bridge's questions.</p></header>
<div class="cards">{''.join(f'<div class="card"><div class="v {cls}">{html.escape(v)}</div><div class="k">{html.escape(k)}</div></div>' for v, k, cls in cards)}</div>
<section><h2>Fidelity by resource type (rehearsal 1)</h2><div class="bars">{bars}</div>
<p>Each field Bridge writes is graded exact → transformed → standardized → inferred → degraded → defaulted → dropped; the bar is the weighted mean per record.
{'<a href="report.html">Full run report (batches, alerts, loss ledger, questions)</a>' if report.exists() else ''}</p></section>
{markdown(transcript)}
<footer>Built {built} by the <code>Conversion demo</code> workflow · <a href="https://github.com/rahulshahepic/synthetic-EHR-conversion">source</a></footer>
</main></body></html>"""
    (site / "index.html").write_text(page, encoding="utf-8")
    (site / "summary.json").write_text(json.dumps({"cards": cards, "fidelity": fids, "built": built}, indent=1))


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "demo_out"), Path(sys.argv[2] if len(sys.argv) > 2 else "site"))
