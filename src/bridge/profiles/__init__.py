"""Source profiles. ``halcyon`` is the hand-written control; any other name loads the profile the
Socratic import builder generated for that source (``bridge/interview/specs/<name>/profile.py``)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

SPECS_DIR = Path(__file__).resolve().parents[1] / "interview" / "specs"


def load_profile(name: str | None) -> ModuleType:
    if not name or name == "halcyon":
        from . import halcyon
        return halcyon
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"not a profile name: {name!r}")
    path = SPECS_DIR / name / "profile.py"
    if not path.exists():
        raise FileNotFoundError(f"no generated profile for {name!r} at {path}")
    spec = importlib.util.spec_from_file_location(f"bridge_generated_profile_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
