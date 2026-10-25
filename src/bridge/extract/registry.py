"""Reader registry: the runner dispatches extract through here.

A reader factory takes a source path and returns ``(export, stage_fn)``
where ``stage_fn(store, run_id, export, profile)`` stages the export's
records. Readers register by name; a profile names its reader via a
``READER`` attribute, defaulting to ``"halcyon"`` — the hand-written
control path, unchanged.

Generated profiles name the generic ``"fixed_width"`` reader. That reader
is binding-driven, so it cannot be a single static factory: dispatch for
it goes through :func:`get_reader_for`, which loads the committed reader
binding for the profile's ``SOURCE_SYSTEM`` and builds the factory from
it. A generated profile is therefore runnable by the Runner exactly as
generated — no hand-registration step.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

ReaderFactory = Callable[[str | Path], tuple[Any, Callable[..., Any]]]

_REGISTRY: dict[str, ReaderFactory] = {}

GENERATED_READER = "fixed_width"
_SPECS_DIR = Path(__file__).resolve().parents[1] / "interview" / "specs"


def register_reader(name: str, factory: ReaderFactory) -> None:
    _REGISTRY[name] = factory


def get_reader(name: str) -> ReaderFactory:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown reader {name!r}; registered: {sorted(_REGISTRY)}") from None


def get_reader_for(name: str, profile: Any = None) -> ReaderFactory:
    """The factory for a reader name, resolving the generated fixed-width
    reader from the profile's committed binding when the name asks for it."""
    if name == GENERATED_READER:
        source_system = getattr(profile, "SOURCE_SYSTEM", None)
        if not source_system:
            raise KeyError(
                "reader 'fixed_width' is generated per source system; the "
                "profile must carry SOURCE_SYSTEM so its committed reader "
                "binding can be loaded")
        binding_path = _SPECS_DIR / source_system / "reader_binding.json"
        if not binding_path.exists():
            raise KeyError(
                f"no committed reader binding for source system "
                f"{source_system!r} at {binding_path}")
        from ..interview.reader import make_factory
        return make_factory(json.loads(binding_path.read_text()))
    return get_reader(name)


def reader_names() -> list[str]:
    return sorted(set(_REGISTRY) | {GENERATED_READER})


def _halcyon_factory(source: str | Path) -> tuple[Any, Callable[..., Any]]:
    from .halcyon import HalcyonExport, stage_all
    return HalcyonExport(source), stage_all


def _fixed_width_factory(source: str | Path) -> tuple[Any, Callable[..., Any]]:
    raise KeyError(
        "reader 'fixed_width' is generated per source system; dispatch "
        "through get_reader_for(name, profile) or reader.make_factory(binding)")


register_reader("halcyon", _halcyon_factory)
register_reader(GENERATED_READER, _fixed_width_factory)
