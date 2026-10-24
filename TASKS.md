# Task Board

How to take a task: see `CONTRIBUTING.md` (claim by pushing branch `task/<ID>-<slug>`; if such a branch exists, it's taken).

Statuses: `ready` · `blocked (<dep>)` · `in-progress (<agent>)` · `review` · `done` · `claude` (reserved for Claude's milestone work — don't take).

For `ready` helper tasks, Claude may have committed a small **v0** implementation so the pipeline runs; the task is to replace it with a robust, spec-complete, well-tested version. Claude will not edit a task's files while it is `in-progress`.

---

## Milestones (reserved)
| ID | Title | Status |
|---|---|---|
| M1 | Nimbus target EHR + import API | done |
| M2 | Halcyon synthetic source generator | claude |
| M3 | Bridge core pipeline, metrics, monitors, pause/revert | claude |
| M5 | MCP server + reconciliation loop | claude |

## Helper tasks

### T-101 · HL7 v2 parser · `ready`
Files: `src/bridge/extract/hl7.py`, `tests/bridge/test_hl7.py`
- `parse_message(text: str) -> Message`; `iter_messages(path: Path) -> Iterator[Message]` (files contain many messages separated by blank lines or `\r\n`/`\n`/`\r` before `MSH`).
- `Message.segments: list[Segment]`, `Message.type` (e.g. `"ADT^A08"`), `Message.control_id`.
- Accessor `msg.get("PID-5.1")`, `msg.get("OBX-5", seg_index=2)`, `msg.get_all("PID-3")` for repetitions (`~`), components (`^`), subcomponents (`&`).
- Honor MSH-1/MSH-2 encoding characters (MSH-1 *is* the field separator); unescape `\F\ \S\ \T\ \R\ \E\ \.br\`.
- Tolerate: trailing separators, missing trailing fields, latin-1 bytes (decode with fallback), Z-segments.
- Acceptance: ≥20 tests including the above edge cases; no third-party HL7 libs.

### T-102 · Free-text medication sig parser · `ready`
Files: `src/bridge/normalize/sig.py`, `tests/bridge/test_sig.py`
- `parse_sig(text: str) -> SigResult` (dataclass) with fields: `dose_value: float | None`, `dose_unit: str | None` (UCUM-ish: `mg`, `mL`, `{tab}`, `{cap}`, `{puff}`, `[iU]`, `{drop}`), `route: str | None` ∈ `oral, iv, im, subcut, topical, inhaled, rectal, ophthalmic, otic, nasal, transdermal, sublingual`, `frequency_count: int | None`, `frequency_period: float | None`, `frequency_period_unit: "h" | "d" | "wk" | None`, `as_needed: bool`, `as_needed_reason: str | None`, `duration_days: int | None`, `confidence: float` (0–1), `unparsed: str` (tokens not understood).
- Handle Latin abbreviations (`po, bid, tid, qid, qd, qhs, q4-6h, prn, ac, pc, x10d, ud`), fractions (`1/2 tab`, `½`), ranges (`1-2 tabs` → take lower bound value, note in `unparsed`? — document your choice), "as directed".
- Acceptance: ≥50 parametrized cases; `confidence < 0.5` whenever any clinically material token is unparsed.

### T-103 · Units and lab value normalization · `in-progress (ChatGPT)`
Files: `src/bridge/normalize/units.py`, `tests/bridge/test_units.py`
- `normalize_unit(raw: str) -> str | None` → UCUM (`"mg/dl"`→`"mg/dL"`, `"MEQ/L"`→`"meq/L"`, `"K/uL"`→`"10*3/uL"`, `"%"`, `"mmHg"` → `"mm[Hg]"`, `"F"`→`"[degF]"`, `"lbs"`→`"[lb_av]"`...). Unknown → `None`.
- `parse_result_value(raw: str) -> ParsedValue` with `kind: "quantity" | "coded" | "string"`, `value: float | None`, `comparator: "<" | "<=" | ">" | ">=" | None`, `code: str | None` (`POS/NEG/DET/ND/TRACE` → `positive/negative/detected/not-detected/trace`), `text: str`.
- `parse_reference_range(raw: str) -> tuple[float | None, float | None]` (`"3.5-5.1"`, `"<200"`, `">=60"`, `"neg"`→`(None, None)`).
- `convert(value, from_unit, to_unit) -> float` for temp (°F↔°C), weight (lb↔kg), height (in↔cm), glucose (mg/dL↔mmol/L).
- Acceptance: ≥40 tests.

### T-104 · Demographic normalizers · `ready`
Files: `src/bridge/normalize/demographics.py`, `tests/bridge/test_demographics.py`
- `parse_name("LAST,FIRST MIDDLE") -> Name(family, given: list[str], suffix: list[str])`; handle `"O'NEIL, MARY-JO"`, `"DE LA CRUZ,JOSE A JR"`, provider style `"SMITH, JOHN Q MD"` (credentials → `suffix`). Title-case smartly (`McDonald`, `O'Neil`, `de la Cruz`).
- `normalize_phone(raw, default_region="US") -> str | None` E.164; handle `(555) 123-4567`, `555.123.4567`, `5551234567x22` (drop ext, flag), `123-4567` (no area code → None).
- `parse_address("123 MAIN ST^APT 4^SPRINGFIELD^IL^62701") -> Address(lines, city, state, postal_code)` and the variants where city/state/zip are crammed into one line.
- `parse_legacy_date("19840312" | "031284" | "00000000" | "1984-03-12") -> DateParse(value: date | None, precision: "day"|"month"|"year"|None, inferred: bool)`. 2-digit years pivot: assume not in future relative to a given `as_of`.
- Acceptance: ≥40 tests.

### T-105 · Synthetic terminology crosswalks · `blocked (M2)`
Files: `src/bridge/terminology/data/*.csv`, `tests/bridge/test_terminology_data.py`
Extend crosswalks so every local code the Halcyon generator can emit (listed in `testbed/halcyon/vocab.py` after M2) has a row or an explicit `unmappable` marker. Include ICD-9→ICD-10 1:many rows. All codes must be labeled synthetic where invented.

### T-106 · Run report renderer · `blocked (M3)`
Files: `src/bridge/report/`, tests
Render a run's metrics, alerts, loss ledger, and question status to a single self-contained HTML file (no external assets) and Markdown.

### T-107 · Web dashboard (stretch) · `blocked (M5)`
Read-only local web UI over the run DB: runs, batches, metric trends, alerts, questions.

### T-108 · Second source profile for drift testing · `blocked (M2)`
Files: `testbed/halcyon/profiles/`
A "Lakeside facility" profile: metric units, different visit codes, different sig style, so the drift monitors have something to catch mid-run.
