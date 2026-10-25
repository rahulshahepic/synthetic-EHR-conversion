"""The profiler: observations about an export, never conclusions.

Reads an export directory and emits a JSON-able report. Two input shapes:

- CSV files (first row is a header), profiled field by field.
- Fixed-width files, when a layout is supplied. Layouts come from the
  export's own shipped layout artifact (for Delphi, ``LAYOUTS.DAT``:
  ``FILE|RT|FIELD|START|LEN|TYPE|DESC``) parsed by :func:`parse_layouts_dat`,
  or from an equivalent in-memory mapping. The profiler never imports a
  source system's generator or layout module — the layout is estate data.

Every field gets an observation record: counts, blank rate, distinct count,
samples, numeric range where applicable, date-shape parse rates (what
fraction of non-blank values *could* be YYMMDD, YYYYMMDD, Julian, HHMM,
minutes-since-midnight), flag-suffix rates for value+flag strings, and the
fraction of values sitting at full field width (a truncation-pile
candidate). Whether any of that *means* something is the interviewer's
question, not the profiler's answer.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_SAMPLES = 5
MAX_DISTINCT_TRACKED = 5000


@dataclass(frozen=True)
class FieldLayout:
    name: str
    start: int  # 0-based
    width: int
    type: str = "T"
    description: str = ""


def parse_layouts_dat(text: str) -> tuple[dict[str, dict[str, list[FieldLayout]]], str | None]:
    """Parse a Delphi-style LAYOUTS.DAT. Returns ({file: {rt: [fields]}}, version)."""
    layouts: dict[str, dict[str, list[FieldLayout]]] = {}
    version: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.search(r"VERSION\s+(\S+)", line)
            if m:
                version = m.group(1)
            continue
        parts = line.split("|")
        if len(parts) < 7 or parts[0] == "FILE":
            continue
        file, rt, name, start, length, typ, desc = parts[:7]
        layouts.setdefault(file, {}).setdefault(rt, []).append(
            FieldLayout(name=name, start=int(start) - 1, width=int(length),
                        type=typ, description=desc))
    for per_file in layouts.values():
        for fields in per_file.values():
            fields.sort(key=lambda f: f.start)
    return layouts, version


# -- date / shape matchers (observations: "could parse as", never "is") ------

def _ymd_ok(mm: int, dd: int) -> bool:
    return 1 <= mm <= 12 and 1 <= dd <= 31


def _shape_rates(values: list[str]) -> dict[str, float]:
    """Fraction of values matching each candidate shape. A value may match
    several shapes; that ambiguity is exactly what the interviewer is for."""
    if not values:
        return {}
    counts = {"YYMMDD": 0, "YYYYMMDD": 0, "JulianYYDDD": 0, "JulianYYYYDDD": 0,
              "HHMM": 0, "minutes_since_midnight": 0, "integer": 0, "decimal": 0}
    for v in values:
        if not v.isdigit():
            continue
        n = len(v)
        if n == 6 and _ymd_ok(int(v[2:4]), int(v[4:6])):
            counts["YYMMDD"] += 1
        if n == 8 and _ymd_ok(int(v[4:6]), int(v[6:8])):
            counts["YYYYMMDD"] += 1
        if n == 5 and 1 <= int(v[2:]) <= 366:
            counts["JulianYYDDD"] += 1
        if n == 7 and 1 <= int(v[4:]) <= 366:
            counts["JulianYYYYDDD"] += 1
        if n == 4 and int(v[:2]) <= 23 and int(v[2:]) <= 59:
            counts["HHMM"] += 1
        if v.lstrip("0").isdigit() and int(v) <= 1439:
            counts["minutes_since_midnight"] += 1
        counts["integer"] += 1
    decimals = sum(1 for v in values if re.fullmatch(r"[+-]?\d+\.\d+", v))
    counts["decimal"] = decimals
    total = len(values)
    return {k: round(c / total, 4) for k, c in counts.items() if c}


_FLAG_RE = re.compile(r"^(?P<num>[<>]?\d+(?:\.\d+)?)(?P<flag>[A-Z]{1,2})$")


def _field_stats(values: list[str], width: int | None) -> dict[str, Any]:
    nonblank = [v for v in values if v != ""]
    stats: dict[str, Any] = {
        "count": len(values),
        "blank_rate": round(1 - len(nonblank) / len(values), 4) if values else 0.0,
    }
    if not nonblank:
        return stats
    distinct = sorted(set(nonblank))
    stats["distinct_count"] = len(distinct) if len(distinct) <= MAX_DISTINCT_TRACKED else MAX_DISTINCT_TRACKED
    stats["samples"] = distinct[:MAX_SAMPLES]
    stats["shape_rates"] = _shape_rates(nonblank)
    numeric = []
    for v in nonblank:
        try:
            numeric.append(float(v))
        except ValueError:
            pass
    if len(numeric) == len(nonblank):
        stats["numeric_min"] = min(numeric)
        stats["numeric_max"] = max(numeric)
    flags = [m.group("flag") for v in nonblank if (m := _FLAG_RE.match(v))]
    if flags:
        stats["flag_suffix_rate"] = round(len(flags) / len(nonblank), 4)
        stats["flag_values"] = sorted(set(flags))[:MAX_SAMPLES]
    if width:
        stats["full_width_rate"] = round(
            sum(1 for v in nonblank if len(v) == width) / len(nonblank), 4)
    stats["max_length"] = max(len(v) for v in nonblank)
    return stats


def _profile_rows(rows: list[dict[str, str]], widths: dict[str, int | None]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in sorted(widths):
        fields[name] = _field_stats([r.get(name, "") for r in rows], widths[name])
    return fields


def profile_export(export_dir: str | Path,
                   layouts: dict[str, dict[str, list[FieldLayout]]] | None = None) -> dict[str, Any]:
    """Profile every data file in an export directory.

    Returns ``{"files": {name: {"records": n, "record_types": {...},
    "fields": {field: stats}}}, "observations": [...]}`` where each field's
    stats carry a stable observation id (``OBS-0001``... in sorted order).
    """
    root = Path(export_dir)
    files: dict[str, Any] = {}
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        stem, suffix = path.stem.upper(), path.suffix.lower()
        if suffix == ".csv":
            with path.open(newline="", encoding="utf-8", errors="replace") as f:
                rows = [{k: (v or "").strip() for k, v in row.items()}
                        for row in csv.DictReader(f)]
            widths = {name: None for name in (rows[0].keys() if rows else [])}
            files[path.name] = {"records": len(rows), "record_types": {"": len(rows)},
                                "fields": _profile_rows(rows, widths)}
        elif layouts and stem in layouts:
            per_rt = layouts[stem]
            by_rt: dict[str, list[dict[str, str]]] = {}
            widths: dict[str, int] = {}
            for raw in path.read_bytes().decode("latin-1").splitlines():
                if not raw.strip():
                    continue
                rt = raw[:2].strip()
                fields = per_rt.get(rt) or next(iter(per_rt.values()))
                row = {}
                for fl in fields:
                    row[fl.name] = raw[fl.start:fl.start + fl.width].strip()
                    widths[fl.name] = fl.width
                by_rt.setdefault(rt, []).append(row)
            all_rows = [r for rows in by_rt.values() for r in rows]
            files[path.name] = {"records": len(all_rows),
                                "record_types": {rt: len(rs) for rt, rs in sorted(by_rt.items())},
                                "fields": _profile_rows(all_rows, widths)}
    observations: list[dict[str, Any]] = []
    n = 0
    for fname in sorted(files):
        for field in sorted(files[fname]["fields"]):
            n += 1
            obs_id = f"OBS-{n:04d}"
            stats = files[fname]["fields"][field]
            stats["observation_id"] = obs_id
            observations.append({"id": obs_id, "file": fname, "field": field,
                                 "kind": "field_profile", "stats": stats})
    return {"files": files, "observations": observations}


def observation_for(report: dict[str, Any], file: str, field: str) -> dict[str, Any] | None:
    for obs in report["observations"]:
        if obs["file"] == file and obs["field"] == field:
            return obs
    return None
