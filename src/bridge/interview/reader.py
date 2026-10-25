"""A generic fixed-width reader driven by a generated reader binding.

The binding is data from the spec (specgen.py): per file, its path in the
export and its record layouts (record type -> field spans). The reader
stages records into plain dicts — source system, record type, record kind,
a source key, and the parsed payload. It knows nothing about any particular
source system; everything source-specific arrived through the interview.
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


def stage_records(export: FixedWidthExport) -> list[dict[str, Any]]:
    """Parse every bound file into staged record dicts (deterministic order)."""
    staged: list[dict[str, Any]] = []
    for stem in sorted(export.files()):
        spec = export.files()[stem]
        fpath = export.path / spec.get("path", f"{stem}.TXT")
        if not fpath.exists():
            continue
        layouts = spec["layouts"]
        key_field = spec.get("key_field")
        for line_no, raw in enumerate(fpath.read_bytes().decode("latin-1").splitlines(), 1):
            if not raw.strip():
                continue
            rt = raw[:2].strip()
            fields = layouts.get(rt) or next(iter(layouts.values()))
            payload = {}
            for fl in fields:
                payload[fl["name"]] = raw[fl["start"]:fl["start"] + fl["width"]].strip()
            staged.append({
                "source_system": export.binding.get("source", "unknown"),
                "record_type": stem,
                "record_kind": rt,
                "source_key": payload.get(key_field) if key_field else payload.get("ACCT"),
                "line": line_no,
                "payload": payload,
            })
    return staged


def make_factory(binding: dict[str, Any]):
    """A reader-registry factory for this binding. The stage function stages
    into record dicts and returns per-type counts; RunStore batch staging
    for generated readers is layered on the same staged records."""
    def factory(source: str | Path):
        export = FixedWidthExport(source, binding)

        def stage_fn(store: Any, run_id: str, exp: FixedWidthExport, profile: Any) -> dict[str, int]:
            records = stage_records(exp)
            counts: dict[str, int] = {}
            for r in records:
                counts[r["record_type"]] = counts.get(r["record_type"], 0) + 1
            return counts

        return export, stage_fn

    return factory
