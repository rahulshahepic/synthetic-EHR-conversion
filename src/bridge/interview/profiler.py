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


def _is_ascii_digits(v: str) -> bool:
    """True for ASCII digit strings only. ``str.isdigit()`` is also true
    for characters like '²' (latin-1 superscripts) that ``int()`` then
    rejects — digit tests in this module must be ASCII-safe."""
    return v.isascii() and v.isdigit()


def _shape_rates(values: list[str]) -> dict[str, float]:
    """Fraction of values matching each candidate shape. A value may match
    several shapes; that ambiguity is exactly what the interviewer is for."""
    if not values:
        return {}
    counts = {"YYMMDD": 0, "YYYYMMDD": 0, "JulianYYDDD": 0, "JulianYYYYDDD": 0,
              "HHMM": 0, "minutes_since_midnight": 0, "integer": 0, "decimal": 0}
    for v in values:
        if not _is_ascii_digits(v):
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
        if int(v) <= 1439:  # "0000" is midnight: it counts
            counts["minutes_since_midnight"] += 1
        counts["integer"] += 1
    decimals = sum(1 for v in values if re.fullmatch(r"[+-]?\d+\.\d+", v))
    counts["decimal"] = decimals
    total = len(values)
    return {k: round(c / total, 4) for k, c in counts.items() if c}


_FLAG_RE = re.compile(r"^(?P<num>[<>]?\d+(?:\.\d+)?)(?P<flag>[A-Z]{1,2})$")
_NUMERIC_LIKE_RE = re.compile(r"^[<>]?\d+(?:\.\d+)?[A-Z]{0,2}$")


def _numeric_like(v: str) -> bool:
    """A value is numeric-like if it is a plain number, a comparator number
    (``>600``), or a number with a flag suffix (``12.4H``). Anything else —
    ``NEG``, ``TRACE``, free text — is a non-numeric value."""
    if _NUMERIC_LIKE_RE.match(v):
        return True
    try:
        float(v)
        return True
    except ValueError:
        return False


def _value_distribution(nonblank: list[str], limit: int) -> dict[str, Any]:
    """Opt-in: the full value distribution of a code-like field (at most ``limit`` distinct
    values), else its most frequent values when they pile up (a placeholder such as a default
    date shows here, where sorted samples would never reach it)."""
    counts: dict[str, int] = {}
    for v in nonblank:
        counts[v] = counts.get(v, 0) + 1
    if len(counts) <= limit:
        return {"value_counts": dict(sorted(counts.items()))}  # signatures add nothing to a full distribution
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    piles = {v: n for v, n in top if n >= 3 and n / len(nonblank) >= 0.005}
    out: dict[str, Any] = {"top_values": piles} if piles else {}
    # Shapes: digits -> 9, letters -> A, everything else kept. Two shapes in one date or code
    # field is how a convention change over time shows up in the data.
    shapes: dict[str, int] = {}
    for v in nonblank:
        s = re.sub(r"[A-Za-z]", "A", re.sub(r"[0-9]", "9", v))
        shapes[s] = shapes.get(s, 0) + 1
    if len(shapes) <= limit:
        out["format_signatures"] = dict(sorted(shapes.items(), key=lambda kv: (-kv[1], kv[0])))
    return out


def _field_stats(values: list[str], width: int | None, code_value_limit: int | None = None) -> dict[str, Any]:
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
    non_numeric = [v for v in nonblank if not _numeric_like(v)]
    if non_numeric:
        stats["non_numeric_rate"] = round(len(non_numeric) / len(nonblank), 4)
        stats["non_numeric_samples"] = sorted(set(non_numeric))[:MAX_SAMPLES]
    if width:
        stats["full_width_rate"] = round(
            sum(1 for v in nonblank if len(v) == width) / len(nonblank), 4)
    stats["max_length"] = max(len(v) for v in nonblank)
    if code_value_limit:
        stats.update(_value_distribution(nonblank, code_value_limit))
    return stats


def _profile_rows(rows: list[dict[str, str]], widths: dict[str, int | None],
                  code_value_limit: int | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in sorted(widths):
        fields[name] = _field_stats([r.get(name, "") for r in rows], widths[name], code_value_limit)
    return fields


def profile_export(export_dir: str | Path,
                   layouts: dict[str, dict[str, list[FieldLayout]]] | None = None,
                   delimited: dict[str, str] | None = None,
                   code_value_limit: int | None = None) -> dict[str, Any]:
    """Profile every data file in an export directory.

    ``delimited`` (``{"suffix": ".dat", "delimiter": "|", "encoding": "latin-1"}``, as the
    estate documents describe the files) profiles header-row delimited files with that suffix
    the same way as CSV files. ``code_value_limit`` adds value distributions (see
    ``_value_distribution``); off by default so recorded observations stay stable.

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
        delim = delimited if delimited and suffix == delimited.get("suffix", "").lower() else None
        if suffix == ".csv" or delim:
            rows: list[dict[str, str]] = []
            ragged = 0
            encoding = delim.get("encoding", "utf-8") if delim else "utf-8"
            dialect = {"delimiter": delim["delimiter"], "quoting": csv.QUOTE_NONE} if delim else {}
            with path.open(newline="", encoding=encoding, errors="replace") as f:
                for raw_row in csv.DictReader(f, **dialect):
                    # A ragged row puts surplus cells under the None key (a
                    # list) and missing cells as None values. Neither may
                    # crash profiling: surplus cells are dropped from the
                    # field view, missing cells read as blank, and the row
                    # is counted in the file's ragged_rows observation.
                    extras = raw_row.pop(None, None)
                    if extras is not None or any(v is None for v in raw_row.values()):
                        ragged += 1
                    rows.append({k: (v or "").strip() for k, v in raw_row.items()})
            widths = {name: None for name in (rows[0].keys() if rows else [])}
            files[path.name] = {"records": len(rows), "record_types": {"": len(rows)},
                                "ragged_rows": ragged,
                                "fields": _profile_rows(rows, widths, code_value_limit)}
        elif layouts and stem in layouts:
            per_rt = layouts[stem]
            by_rt: dict[str, list[dict[str, str]]] = {}
            widths: dict[str, int] = {}
            unknown: dict[str, int] = {}
            for raw in path.read_bytes().decode("latin-1").splitlines():
                if not raw.strip():
                    continue
                rt = raw[:2].strip()
                fields = per_rt.get(rt)
                if fields is None:
                    # An unrecognized record type is an observation, never
                    # a row silently parsed with the first layout.
                    unknown[rt] = unknown.get(rt, 0) + 1
                    continue
                row = {}
                for fl in fields:
                    row[fl.name] = raw[fl.start:fl.start + fl.width].strip()
                    widths[fl.name] = fl.width
                by_rt.setdefault(rt, []).append(row)
            all_rows = [r for rows in by_rt.values() for r in rows]
            entry: dict[str, Any] = {"records": len(all_rows),
                                     "record_types": {rt: len(rs) for rt, rs in sorted(by_rt.items())},
                                     "fields": _profile_rows(all_rows, widths, code_value_limit)}
            if unknown:
                entry["unknown_record_types"] = unknown
            files[path.name] = entry
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


def value_shape_claims(report: dict[str, Any], min_rate: float = 0.01,
                       max_rate: float = 0.5) -> list:
    """Profiler-side value-shape claims, from the report's own statistics.

    A predominantly numeric field carrying a material minority of
    non-numeric text is exactly where an analyst belief like "non-numeric
    values are bench errors, exclude them" can be wrong without anyone
    noticing: the belief enters the claim store unopposed and the spec
    adopts it. For every such field this emits a claim — sourced to the
    field's profiler observation — stating the observed mix, so the belief
    collides with data and opens a dispute instead of being swallowed.
    Purely or mostly textual fields (names, note text, phone numbers)
    emit nothing: there is no numeric convention for them to dispute.
    """
    from .claims import Claim
    out = []
    for obs in report.get("observations", []):
        stats = obs.get("stats") or {}
        rate = stats.get("non_numeric_rate") or 0.0
        if rate < min_rate or rate > max_rate:
            continue
        samples = stats.get("non_numeric_samples") or []
        value = (f"mixed numeric and non-numeric values: {rate:.1%} of values are "
                 f"non-numeric text"
                 + (f" (samples: {', '.join(samples)})" if samples else "")
                 + "; non-numeric values are present in the data and carried as text")
        out.append(Claim(subject=f"field:{obs['file']}.{obs['field']}",
                         predicate="convention", value=value, source=obs["id"],
                         source_kind="profiler-data", evidence_refs=(obs["id"],)))
    return out
