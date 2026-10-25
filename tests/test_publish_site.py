"""The Pages archive keeps old URLs and prunes only reports outside retention."""
from __future__ import annotations

import json
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
