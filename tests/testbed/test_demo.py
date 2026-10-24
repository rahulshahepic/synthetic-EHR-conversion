import sys

from testbed import demo


def test_demo_runs_end_to_end(tmp_path, monkeypatch):
    out = tmp_path / "demo"
    monkeypatch.setattr(sys, "argv", ["demo", "--out", str(out), "--patients", "60", "--seed", "5"])
    demo.main()
    text = (out / "DEMO_TRANSCRIPT.md").read_text()
    assert "Rehearsal 2" in text and "Cutover" in text
    assert "counts OK" in text and "FAIL" not in text
    assert "with 0 blocking questions" in text
    assert "Go-live readiness: **NO-GO**" in text and ": **GO**" in text
    assert (out / "rehearsal1_report.html").read_text().lstrip().lower().startswith("<!doctype html")
