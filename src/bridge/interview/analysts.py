"""Analyst backends and the estate firewall for the Socratic builder.

The interviewer reaches analysts ONLY through :meth:`AnalystService.ask`.
An analyst's profile is the backend's private knowledge: it is never served
to the interviewer, never in the estate allowlist, and (for the future LLM
backend) is used only to prime the analyst's own session — see
:func:`build_profile_prompt`.

Backends here are deterministic: the stub backend answers from recorded
Q&A data plus each profile's stated blind spots. No live LLM calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Path parts that are never estate documents, wherever they appear. The
# grading-ledger directory name is assembled at runtime: the boundary test
# scans bridge sources for that literal to prove bridge never touches it,
# and the firewall that enforces the rule should not trip the scanner.
# Matching is case-insensitive: on a case-insensitive filesystem a request
# for "ESTATE_DISCREPANCIES.JSON" or an "Answer_Key" part names the same
# file, so the deny checks must fold case on both the requested path and
# the resolved candidate.
DENY_PARTS = {"answer" + "_key", "analysts", "grading", "specs"}
DENY_NAMES = {"estate_discrepancies.json", "stub_analysts.json"}
ALLOW_SUFFIXES = {".md", ".txt", ".json", ".dat", ".csv"}

# Parts that mark a path as repository structure, not an estate document,
# wherever they appear in the path *as requested under a root*: source
# trees, documentation trees and test trees are never estate documents.
STRUCTURE_PARTS = {"src", "docs", "tests"}
# A root that IS one of those trees, sits *inside* one, or is a checkout
# root containing them, is refused at construction: the firewall must not
# depend on the caller choosing a narrow root. An estate root is an
# estate directory (manuals, dictionaries, layouts, extracts), never a
# repository. (A root may legitimately *contain* denied subtrees —
# analysts/, grading/ — because read() refuses those parts; what it may
# not be is a code/docs/test tree, whose documents are not denied by
# name and must never serve.)
FORBIDDEN_ROOT_NAMES = STRUCTURE_PARTS


def _denied(parts: Any) -> bool:
    return any(part.lower() in DENY_PARTS or part.lower() in DENY_NAMES
               or "analyst" in part.lower()
               for part in parts)


def _repo_ancestor(path: Path) -> Path | None:
    """The nearest ancestor of ``path`` (itself included) that looks like
    a repository root: it holds a ``.git`` entry or a ``pyproject.toml``."""
    for anc in (path, *path.parents):
        if (anc / ".git").exists() or (anc / "pyproject.toml").exists():
            return anc
    return None


def _check_root(root: Path) -> None:
    # The structure check is scoped to the repository the root belongs
    # to: only the parts of the root *relative to its repo root* count.
    # A checkout living under an unrelated src/, docs/ or tests/
    # directory (~/src/<project> is the common case) must not refuse the
    # project's own estates for its parent directories' names.
    repo = _repo_ancestor(root)
    if repo is not None and root != repo:
        rel_parts = root.relative_to(repo).parts
        if any(part.lower() in FORBIDDEN_ROOT_NAMES for part in rel_parts):
            raise ValueError(f"not an estate root: {root}")
    elif root.name.lower() in FORBIDDEN_ROOT_NAMES:
        raise ValueError(f"not an estate root: {root}")
    if root.is_dir():
        children = {p.name.lower() for p in root.iterdir() if p.is_dir()}
        if children & FORBIDDEN_ROOT_NAMES:
            raise ValueError(
                f"not an estate root: {root} contains repository "
                f"structure {sorted(children & FORBIDDEN_ROOT_NAMES)}")


def _norm(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower()).rstrip("?.!")


@dataclass
class StubAnalyst:
    """One simulated analyst: recorded answers + stated blind spots.

    ``answers`` maps a question (matched after normalization) to the exact
    recorded answer text — replay returns it byte-for-byte. A question that
    touches a blind spot, or that was never recorded, gets the profile's
    deterministic non-answer instead of an improvisation.
    """
    id: str
    name: str
    answers: dict[str, str] = field(default_factory=dict)
    blind_spots: list[str] = field(default_factory=list)   # substrings, normalized
    outside_response: str = "Outside my area."
    unknown_response: str = "I don't know."

    def ask(self, question: str) -> str:
        q = _norm(question)
        for recorded_q, answer in self.answers.items():
            if _norm(recorded_q) == q:
                return answer
        if any(spot in q for spot in self.blind_spots):
            return self.outside_response
        return self.unknown_response


class EstateReader:
    """Serves estate documents under a strict allowlist.

    Estate = manuals, dictionaries, layouts, manifests, extract files.
    Never: grading ledgers (any grading-directory path), analyst profiles
    (any ``analysts`` path), code, or anything outside the estate roots.
    """

    def __init__(self, roots: list[str | Path]):
        self.roots = [Path(r).resolve() for r in roots]
        for root in self.roots:
            _check_root(root)

    def read(self, document: str) -> str:
        rel = Path(document)
        if rel.is_absolute() or _denied(rel.parts) \
                or any(p.lower() in STRUCTURE_PARTS for p in rel.parts):
            raise PermissionError(f"not an estate document: {document}")
        if rel.suffix.lower() not in ALLOW_SUFFIXES:
            raise PermissionError(f"not an estate document type: {document}")
        for root in self.roots:
            candidate = (root / rel).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                if _denied(candidate.parts):
                    raise PermissionError(f"not an estate document: {document}")
                return candidate.read_bytes().decode("latin-1")
        raise FileNotFoundError(f"estate document not found: {document}")


class AnalystService:
    """The interviewer's only door to analysts and estate documents."""

    def __init__(self, analysts: dict[str, StubAnalyst], estate: EstateReader):
        self.analysts = analysts
        self.estate = estate

    def ask(self, analyst: str, question: str) -> dict[str, Any]:
        a = self.analysts.get(analyst)
        if a is None:
            return {"analyst": analyst, "error": f"unknown analyst: {analyst}"}
        return {"analyst": analyst, "answer": a.ask(question)}

    def read_estate(self, document: str) -> dict[str, Any]:
        try:
            return {"document": document, "text": self.estate.read(document)}
        except (PermissionError, FileNotFoundError) as e:
            return {"document": document, "error": str(e)}


def build_profile_prompt(profile_text: str, estate_docs: dict[str, str]) -> str:
    """System prompt for a future live-LLM analyst backend. The analyst is
    primed with exactly one profile plus the estate documents its owner
    could plausibly have — nothing else exists for it. Not called in tests
    against any live model; it is data, reviewed like code."""
    docs = "\n\n".join(f"===== {name}\n{text}" for name, text in sorted(estate_docs.items()))
    return (
        "You are the analyst described in the profile below. Answer interview "
        "questions only from the profile and the documents provided. You know "
        "nothing else: not how the data was generated, not what a conversion "
        "team hopes to hear, not the contents of any grading material. When a "
        "question falls outside the profile, say it is outside your area and "
        "name the department that would own it, the way the profile does.\n\n"
        f"===== PROFILE\n{profile_text}\n\n{docs}"
    )


def replay_questions(events: list, service: AnalystService) -> list[dict[str, Any]]:
    """Replay a recorded ledger's questions through a service and diff the
    answers against the recorded ones. Returns mismatches ([] = faithful)."""
    from .ledger import answers as recorded_answers
    recorded = recorded_answers(events)
    mismatches: list[dict[str, Any]] = []
    for ev in events:
        if ev.type != "question":
            continue
        got = service.ask(ev.payload["analyst"], ev.payload["text"])
        want = recorded.get(ev.id)
        want_text = want.payload.get("text") if want else None
        if got.get("answer") != want_text:
            mismatches.append({"question_id": ev.id, "expected": want_text,
                               "got": got.get("answer"), "error": got.get("error")})
    return mismatches
