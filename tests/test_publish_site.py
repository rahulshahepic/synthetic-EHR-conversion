"""The Pages archive keeps old URLs and prunes only reports outside retention."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.publish_site import MAX_RUNS, branch_slug, publish


SHA = "a" * 40


def built_site(path: Path, label: str) -> Path:
    path.mkdir()
    (path / "index.html").write_text(label)
    (path / "report.html").write_text(f"report {label}")
    return path


def test_history_aliases_and_retention(tmp_path: Path) -> None:
    site = built_site(tmp_path / "site", "first")
    archive = tmp_path / "archive"
    publish(site, archive, "1", "1", "main", SHA)
    original = archive / f"runs/{branch_slug('main')}/1-1"
    assert (original / "report.html").read_text() == "report first"

    for run_id in range(2, MAX_RUNS + 3):
        (site / "index.html").write_text(f"run {run_id}")
        publish(site, archive, str(run_id), "1", "feature/a", SHA)

    runs = json.loads((archive / "runs.json").read_text())
    assert len(runs) == MAX_RUNS
    assert (original / "index.html").read_text() == "first"  # latest main pinned
    assert not (archive / f"runs/{branch_slug('feature/a')}/2-1").exists()
    assert (archive / f"runs/{branch_slug('feature/a')}/{MAX_RUNS + 2}-1").exists()
    assert f"{MAX_RUNS + 2}-1" in (archive / "branches" / branch_slug("feature/a") / "index.html").read_text()
    assert "Latest main demo" in (archive / "index.html").read_text()
    assert (archive / ".nojekyll").exists()


def test_rerun_and_hostile_branch_name(tmp_path: Path) -> None:
    site = built_site(tmp_path / "site", "attempt 1")
    archive = tmp_path / "archive"
    branch = "feature/../<script>"
    publish(site, archive, "42", "1", branch, SHA)
    (site / "index.html").write_text("attempt 2")
    publish(site, archive, "42", "2", branch, SHA)
    assert len(json.loads((archive / "runs.json").read_text())) == 2
    assert (archive / f"runs/{branch_slug(branch)}/42-1/index.html").read_text() == "attempt 1"
    assert "<script>" not in (archive / "index.html").read_text()
    assert "&lt;script&gt;" in (archive / "index.html").read_text()
    assert ".." not in branch_slug(branch)


def test_rejects_invalid_identifiers(tmp_path: Path) -> None:
    site = built_site(tmp_path / "site", "ok")
    with pytest.raises(ValueError):
        publish(site, tmp_path / "archive", "../1", "1", "main", SHA)


def test_archive_script_preserves_runs_after_first_publication(tmp_path: Path) -> None:
    """Exercise the actual Git steps in fresh checkouts, as Actions does."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(origin)], check=True, capture_output=True)
    source_tools = Path(__file__).resolve().parents[1] / "tools"

    def checkout(name: str, label: str) -> Path:
        dest = tmp_path / name
        subprocess.run(["git", "clone", str(origin), str(dest)], check=True, capture_output=True)
        (dest / "tools").mkdir(exist_ok=True)
        for file in ("archive_pages.sh", "publish_site.py"):
            shutil.copy(source_tools / file, dest / "tools" / file)
        (dest / "site").mkdir()
        (dest / "site" / "index.html").write_text(label)
        return dest

    first = checkout("first", "first report")
    subprocess.run(["git", "-C", str(first), "add", "tools"], check=True)
    subprocess.run(["git", "-C", str(first), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-m", "fixture"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(first), "push", "origin", "HEAD:main"], check=True, capture_output=True)

    for checkout_dir, run_id in ((first, "123"), (checkout("second", "second report"), "124")):
        sha = subprocess.check_output(["git", "-C", str(checkout_dir), "rev-parse", "HEAD"], text=True).strip()
        runner_temp = tmp_path / f"runner-{run_id}"
        runner_temp.mkdir()
        env = os.environ | {"RUNNER_TEMP": str(runner_temp), "GITHUB_RUN_ID": run_id,
                            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF_NAME": "main", "GITHUB_SHA": sha}
        subprocess.run(["bash", "tools/archive_pages.sh"], cwd=checkout_dir, env=env, check=True, capture_output=True)

    subprocess.run(["git", "-C", str(first), "fetch", "origin", "gh-pages"], check=True, capture_output=True)
    manifest = subprocess.check_output(["git", "-C", str(first), "show", "FETCH_HEAD:runs.json"], text=True)
    assert [r["run_id"] for r in json.loads(manifest)] == [124, 123]
