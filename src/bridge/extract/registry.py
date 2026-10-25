"""Reader registry: the runner dispatches extract through here.

A reader factory takes a source path and returns ``(export, stage_fn)``
where ``stage_fn(store, run_id, export, profile)`` stages the export's
records. Readers register by name; a profile names its reader via a
``READER`` attribute, defaulting to ``"halcyon"`` — the hand-written
control path, unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

ReaderFactory = Callable[[str | Path], tuple[Any, Callable[..., Any]]]

_REGISTRY: dict[str, ReaderFactory] = {}


def register_reader(name: str, factory: ReaderFactory) -> None:
    _REGISTRY[name] = factory


def get_reader(name: str) -> ReaderFactory:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown reader {name!r}; registered: {sorted(_REGISTRY)}") from None


def reader_names() -> list[str]:
    return sorted(_REGISTRY)


def _halcyon_factory(source: str | Path) -> tuple[Any, Callable[..., Any]]:
    from .halcyon import HalcyonExport, stage_all
    return HalcyonExport(source), stage_all


register_reader("halcyon", _halcyon_factory)
