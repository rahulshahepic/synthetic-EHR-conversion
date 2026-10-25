"""Add a demo site to the persistent GitHub Pages archive.

Usage: python tools/publish_site.py SITE ARCHIVE RUN_ID ATTEMPT BRANCH SHA
The archive is the checked-out gh-pages branch; SITE is the fresh build.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_RUNS = 20


def branch_slug(branch: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")[:48].rstrip("-") or "branch"
    return f"{readable}-{hashlib.sha256(branch.encode()).hexdigest()[:8]}"


def write_index(archive: Path, runs: list[dict]) -> None:
    rows = []
    for run in runs:
        link = html.escape(run["path"], quote=True)
        branch = html.escape(run["branch"])
        sha = html.escape(run["sha"][:12])
        created = html.escape(run["published"])
        rows.append(f'<li><a href="{link}">{branch} · run {run["run_id"]}, attempt {run["attempt"]}</a>'
                    f' <small>({sha}, {created})</small></li>')
    latest_main = next((r for r in runs if r["branch"] == "main"), None)
    latest_link = (f'<p><a href="{html.escape(latest_main["path"], quote=True)}">Latest main demo</a></p>'
                   if latest_main else "")
    (archive / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width, initial-scale=1"><title>Bridge demo runs</title>'
        '<style>body{font:16px/1.6 system-ui;max-width:800px;margin:3rem auto;padding:0 1rem}'
        'li{margin:.6rem 0}small{color:#555}</style><h1>Bridge conversion demos</h1>'
        '<p>Synthetic EHR conversions. Up to 20 successful runs are retained, including the newest main run.</p>'
        f'{latest_link}<ol>{"".join(rows)}</ol></html>', encoding="utf-8")


def publish(site: Path, archive: Path, run_id: str, attempt: str, branch: str, sha: str) -> None:
    if not re.fullmatch(r"[1-9][0-9]*", run_id) or not re.fullmatch(r"[1-9][0-9]*", attempt):
        raise ValueError("run ID and attempt must be positive integers")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ValueError("SHA must be a full commit hash")
    if not branch or not (site / "index.html").is_file():
        raise ValueError("branch and built site/index.html are required")

    archive.mkdir(parents=True, exist_ok=True)
    manifest = archive / "runs.json"
    runs = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    path = f"runs/{branch_slug(branch)}/{run_id}-{attempt}/"
    target = archive / path
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(site, target)
    runs = [r for r in runs if r["path"] != path]
    runs.append({"run_id": int(run_id), "attempt": int(attempt), "branch": branch,
                 "sha": sha.lower(), "published": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "path": path})
    runs.sort(key=lambda r: (r["run_id"], r["attempt"]), reverse=True)
    kept = runs[:MAX_RUNS]
    latest_main = next((r for r in runs if r["branch"] == "main"), None)
    if latest_main and latest_main not in kept:
        kept[-1] = latest_main
        kept.sort(key=lambda r: (r["run_id"], r["attempt"]), reverse=True)
    for run in runs:
        if run not in kept:
            shutil.rmtree(archive / run["path"])
    # Rebuild aliases from the retained runs. All relative links work at the
    # repository's GitHub Pages base path, with or without a custom domain.
    aliases = archive / "branches"
    if aliases.exists():
        shutil.rmtree(aliases)
    for run in kept:
        alias = aliases / branch_slug(run["branch"])
        if alias.exists():
            continue
        alias.mkdir(parents=True)
        dest = f"../../{run['path']}"
        (alias / "index.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url={html.escape(dest, quote=True)}">'
            f'<a href="{html.escape(dest, quote=True)}">Open latest run</a>', encoding="utf-8")
    manifest.write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    (archive / ".nojekyll").touch()
    write_index(archive, kept)


if __name__ == "__main__":
    publish(Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:7])
