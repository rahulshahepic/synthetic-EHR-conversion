"""A generic fixed-width reader driven by a generated reader binding.

The binding is data from the spec (specgen.py): per file, its path in the
export and its record layouts (record type -> field spans), the record
type discriminator's position, and the key fields per record kind. The
reader stages records into plain dicts — source system, record type,
record kind, a source key, and the parsed payload. It knows nothing about
any particular source system; everything source-specific arrived through
the interview, and everything Delphi-shaped (a two-character record type
at offset 0, an ACCT key) must arrive *through the binding*, never as a
hardcoded fallback here.

Strictness is the point: a bound file that is missing, a record whose
discriminator names no layout in the binding, a row too short for its
layout, and a record with no key are all loud errors. A reader that
silently skips or guesses is how a run "completes" with records missing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FixedWidthExport:
    def __init__(self, path: str | Path, binding: dict[str, Any]):
        self.path = Path(path)
        self.binding = binding
        manifest_path = self.path / "manifest.json"
        self.manifest: dict[str, Any] = (json.loads(manifest_path.read_text())
                                         if manifest_path.exists() else {})

    def files(self) -> dict[str, Any]:
        return self.binding.get("files", {})


def _discriminator(spec: dict[str, Any]) -> tuple[int, int]:
    """(start, width) of the record-type discriminator, from the binding.

    Defaults to the whole layout's keying convention: when the binding
    omits it, the discriminator is the span of the layout's ``RT`` field;
    a binding with neither is rejected rather than guessed at.
    """
    disc = spec.get("discriminator") or {}
    if "start" in disc or "width" in disc:
        return int(disc.get("start", 0)), int(disc.get("width", 2))
    for fields in spec["layouts"].values():
        for fl in fields:
            if fl["name"] == "RT":
                return int(fl["start"]), int(fl["width"])
    raise ValueError("reader binding carries no discriminator and no RT field span")


def _key_fields(spec: dict[str, Any], record_kind: str, stem: str) -> list[str]:
    """The key field(s) for one record kind, from the binding.

    ``key_fields`` maps record kind -> a field name or a list of field
    names (composite key); a plain string/list applies to every kind. The
    legacy singular ``key_field`` is still honored. No binding key
    information is an error — inventing a key (say, ACCT) for files that
    have none is how keyless and colliding records get staged.
    """
    key_fields = spec.get("key_fields")
    entry: Any = None
    if isinstance(key_fields, dict):
        entry = key_fields.get(record_kind, key_fields.get("*"))
    elif key_fields is not None:
        entry = key_fields
    if entry is None:
        entry = spec.get("key_field")
    if entry is None:
        raise ValueError(
            f"reader binding for {stem} declares no key field for record "
            f"kind {record_kind!r}")
    return [entry] if isinstance(entry, str) else list(entry)


def stage_records(export: FixedWidthExport) -> list[dict[str, Any]]:
    """Parse every bound file into staged record dicts (deterministic order).

    Raises on a missing required file, an unknown record discriminator, a
    row shorter than its layout, a missing key value, a duplicate
    (record_type, source_key) pair, and a parsed count that disagrees with
    the export manifest.
    """
    staged: list[dict[str, Any]] = []
    manifest_counts = export.manifest.get("counts", {})
    for stem in sorted(export.files()):
        spec = export.files()[stem]
        fpath = export.path / spec.get("path", f"{stem}.TXT")
        if not fpath.exists():
            if spec.get("optional"):
                # Optional permits absence only when the delivery agrees
                # the file is empty: a positive manifest count for a
                # missing file is a contradiction, not an option.
                expected = manifest_counts.get(stem)
                if expected:
                    raise ValueError(
                        f"bound file missing from export: {fpath} but the "
                        f"export manifest counts {expected} records for "
                        f"{stem}")
                continue
            raise FileNotFoundError(
                f"bound file missing from export: {fpath} "
                f"(binding for {stem} does not mark it optional)")
        layouts = spec["layouts"]
        start, width = _discriminator(spec)
        seen_keys: set[str] = set()
        parsed = 0
        for line_no, raw in enumerate(fpath.read_bytes().decode("latin-1").splitlines(), 1):
            if not raw.strip():
                continue
            rt = raw[start:start + width].strip()
            fields = layouts.get(rt)
            if fields is None:
                raise ValueError(
                    f"{fpath.name} line {line_no}: unknown record type "
                    f"{rt!r}; the binding defines {sorted(layouts)}")
            need = max(fl["start"] + fl["width"] for fl in fields)
            if len(raw) < need:
                raise ValueError(
                    f"{fpath.name} line {line_no}: row of {len(raw)} chars is "
                    f"shorter than the {rt!r} layout's {need} chars")
            payload = {}
            for fl in fields:
                payload[fl["name"]] = raw[fl["start"]:fl["start"] + fl["width"]].strip()
            key_parts = []
            for name in _key_fields(spec, rt, stem):
                v = payload.get(name)
                if not v:
                    raise ValueError(
                        f"{fpath.name} line {line_no}: record kind {rt!r} has "
                        f"no value for key field {name!r}")
                key_parts.append(v)
            source_key = "|".join(key_parts)
            if source_key in seen_keys:
                raise ValueError(
                    f"{fpath.name} line {line_no}: duplicate source key "
                    f"{source_key!r} for record type {stem}")
            seen_keys.add(source_key)
            parsed += 1
            staged.append({
                "source_system": export.binding.get("source", "unknown"),
                "record_type": stem,
                "record_kind": rt,
                "source_key": source_key,
                "line": line_no,
                "payload": payload,
            })
        expected = manifest_counts.get(stem)
        if expected is not None and parsed != expected:
            raise ValueError(
                f"{fpath.name}: parsed {parsed} records but the export "
                f"manifest counts {expected}")
    return staged


def make_factory(binding: dict[str, Any]):
    """A reader-registry factory for this binding. The stage function
    persists every staged record into the run store (grouped by record
    type, with file/line lineage) and returns per-type counts of the
    records actually staged."""
    def factory(source: str | Path):
        export = FixedWidthExport(source, binding)

        def stage_fn(store: Any, run_id: str, exp: FixedWidthExport, profile: Any) -> dict[str, int]:
            records = stage_records(exp)
            by_type: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
            for r in records:
                payload = dict(r["payload"])
                payload["_record_kind"] = r["record_kind"]
                payload["_line"] = r["line"]
                payload["_source_system"] = r["source_system"]
                lineage = {"channel": "fixed_width",
                           "file": f"{r['record_type']}.TXT",
                           "line": r["line"],
                           "record_kind": r["record_kind"]}
                by_type.setdefault(r["record_type"], []).append(
                    (r["source_key"], payload, lineage))
            counts: dict[str, int] = {}
            for rtype in sorted(by_type):
                counts[rtype] = store.stage(run_id, rtype, by_type[rtype])
            return counts

        return export, stage_fn

    return factory
