"""The Socratic import builder: Bridge learns a source system from its
documentary estate and analyst interviews, and generates the import spec
with provenance. See docs/socratic-import-builder.md.

Hard rules for this package:
- It reads estate files (exports, dictionaries, manuals, analyst profiles)
  only. It never reads a source's grading ledger and never imports a
  testbed or a generator.
- Everything it believes is a claim with provenance (claims.py).
- Interviews are data: append-only ledgers (ledger.py) replay
  deterministically in tests; no live LLM calls anywhere in this package.
"""
from __future__ import annotations
