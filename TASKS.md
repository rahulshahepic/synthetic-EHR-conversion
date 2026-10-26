# Task Board

How to take a task: see `CONTRIBUTING.md` (claim by pushing branch `task/<ID>-<slug>`; if such a branch exists, it's taken).

Statuses: `ready` · `blocked (<dep>)` · `in-progress (<agent>)` · `review` · `done` · `claude` (reserved for Claude's milestone work — don't take).

For `ready` helper tasks, Claude may have committed a small **v0** implementation so the pipeline runs; the task is to replace it with a robust, spec-complete, well-tested version. Claude will not edit a task's files while it is `in-progress`.

---

## Milestones (reserved)
| ID | Title | Status |
|---|---|---|
| M1 | Nimbus target EHR + import API | done |
| M2 | Halcyon synthetic source generator | done |
| M3 | Bridge core pipeline, metrics, monitors, pause/revert | done |
| M4 | Remaining domains + HL7 ORU/SIU + CSV channels | done |
| M5 | MCP server + reconciliation loop | done |
| M6 | Verification: read-back sampling, clinical sentinels, end-of-run reconciliation | done |
| M7 | Rehearsals: rule carry-over, run-vs-run comparison | done |
| M8 | Cutover delta load + source deletions | done |
| M9 | Late identity merges via Nimbus $merge | done |
| M10 | Scripted end-to-end demo | done |
| M11 | Second source system (Lakeside) onboarding | done |
| M12 | Ask the user natively via MCP elicitation | done |
| M13 | Go-live readiness + sign-offs | done |

## Helper tasks

### T-114 · Keep distinct GitHub Pages demo runs · `done`
Files: `.github/workflows/demo.yml`, `tools/archive_pages.sh`, `tools/publish_site.py`, `tests/test_publish_site.py`, `README.md`.
Publish each successful demo under a branch and Actions run/attempt path. Show retained runs at the site root and link each branch's latest run. Keep at most 20 reports, preserving the newest main run. Persist the archive across Pages deployments and handle simultaneous workflow runs safely.

### T-101 · HL7 v2 parser · `done`
Files: `src/bridge/extract/hl7.py`, `tests/bridge/test_hl7.py`
- `parse_message(text: str) -> Message`; `iter_messages(path: Path) -> Iterator[Message]` (files contain many messages separated by blank lines or `\r\n`/`\n`/`\r` before `MSH`).
- `Message.segments: list[Segment]`, `Message.type` (e.g. `"ADT^A08"`), `Message.control_id`.
- Accessor `msg.get("PID-5.1")`, `msg.get("OBX-5", seg_index=2)`, `msg.get_all("PID-3")` for repetitions (`~`), components (`^`), subcomponents (`&`).
- Honor MSH-1/MSH-2 encoding characters (MSH-1 *is* the field separator); unescape `\F\ \S\ \T\ \R\ \E\ \.br\`.
- Tolerate: trailing separators, missing trailing fields, latin-1 bytes (decode with fallback), Z-segments.
- Acceptance: ≥20 tests including the above edge cases; no third-party HL7 libs.

### T-102 · Free-text medication sig parser · `done`
Files: `src/bridge/normalize/sig.py`, `tests/bridge/test_sig.py`
- `parse_sig(text: str) -> SigResult` (dataclass) with fields: `dose_value: float | None`, `dose_unit: str | None` (UCUM-ish: `mg`, `mL`, `{tab}`, `{cap}`, `{puff}`, `[iU]`, `{drop}`), `route: str | None` ∈ `oral, iv, im, subcut, topical, inhaled, rectal, ophthalmic, otic, nasal, transdermal, sublingual`, `frequency_count: int | None`, `frequency_period: float | None`, `frequency_period_unit: "h" | "d" | "wk" | None`, `as_needed: bool`, `as_needed_reason: str | None`, `duration_days: int | None`, `confidence: float` (0–1), `unparsed: str` (tokens not understood).
- Handle Latin abbreviations (`po, bid, tid, qid, qd, qhs, q4-6h, prn, ac, pc, x10d, ud`), fractions (`1/2 tab`, `½`), ranges (`1-2 tabs` → take lower bound value, note in `unparsed`? — document your choice), "as directed".
- Acceptance: ≥50 parametrized cases; `confidence < 0.5` whenever any clinically material token is unparsed.

### T-103 · Units and lab value normalization · `done`
Files: `src/bridge/normalize/units.py`, `tests/bridge/test_units.py`
- `normalize_unit(raw: str) -> str | None` → UCUM (`"mg/dl"`→`"mg/dL"`, `"MEQ/L"`→`"meq/L"`, `"K/uL"`→`"10*3/uL"`, `"%"`, `"mmHg"` → `"mm[Hg]"`, `"F"`→`"[degF]"`, `"lbs"`→`"[lb_av]"`...). Unknown → `None`.
- `parse_result_value(raw: str) -> ParsedValue` with `kind: "quantity" | "coded" | "string"`, `value: float | None`, `comparator: "<" | "<=" | ">" | ">=" | None`, `code: str | None` (`POS/NEG/DET/ND/TRACE` → `positive/negative/detected/not-detected/trace`), `text: str`.
- `parse_reference_range(raw: str) -> tuple[float | None, float | None]` (`"3.5-5.1"`, `"<200"`, `">=60"`, `"neg"`→`(None, None)`).
- `convert(value, from_unit, to_unit) -> float` for temp (°F↔°C), weight (lb↔kg), height (in↔cm), glucose (mg/dL↔mmol/L).
- Acceptance: ≥40 tests.

### T-104 · Demographic normalizers · `done`
Files: `src/bridge/normalize/demographics.py`, `tests/bridge/test_demographics.py`
- `parse_name("LAST,FIRST MIDDLE") -> Name(family, given: list[str], suffix: list[str])`; handle `"O'NEIL, MARY-JO"`, `"DE LA CRUZ,JOSE A JR"`, provider style `"SMITH, JOHN Q MD"` (credentials → `suffix`). Title-case smartly (`McDonald`, `O'Neil`, `de la Cruz`).
- `normalize_phone(raw, default_region="US") -> str | None` E.164; handle `(555) 123-4567`, `555.123.4567`, `5551234567x22` (drop ext, flag), `123-4567` (no area code → None).
- `parse_address("123 MAIN ST^APT 4^SPRINGFIELD^IL^62701") -> Address(lines, city, state, postal_code)` and the variants where city/state/zip are crammed into one line.
- `parse_legacy_date("19840312" | "031284" | "00000000" | "1984-03-12") -> DateParse(value: date | None, precision: "day"|"month"|"year"|None, inferred: bool)`. 2-digit years pivot: assume not in future relative to a given `as_of`.
- Acceptance: ≥40 tests.

### T-105 · Synthetic terminology crosswalks · `done`
Files: `src/bridge/terminology/data/*.csv`, `tests/bridge/test_terminology_data.py`
Today several local codes intentionally have no crosswalk row, so they become reconciliation questions (e.g. `HZ099`, unrecognized specialty/race text, uncodable allergens). Write a script `tools/crosswalk_gaps.py` that runs a conversion on a generated export and lists every question kind+key that a crosswalk row could have prevented; then extend the CSVs (keep a few deliberate gaps, documented in `data/README.md`) so that every local code in `testbed/halcyon/vocab.py` either maps or is listed as a deliberate gap. Include ICD-9→ICD-10 1:many rows. All codes must be labeled synthetic where invented.

### T-106 · Run report renderer · `done`
Files: `src/bridge/report/`, tests
Render a run's metrics, alerts, loss ledger, and question status to a single self-contained HTML file (no external assets) and Markdown.
Read only through `bridge.runs.store.RunStore` and `bridge.status` (`run_summary`, `metrics_view`, `loss_summary`). Add a CLI subcommand `report --out <file.html>`. Test against a run produced by the fixtures in `tests/bridge/conftest.py`.

### T-107 · Web dashboard (stretch) · `done`
Files: `src/bridge/web/` (new), tests.
Read-only local web UI over the run DB: runs, batches, metric trends, alerts, questions, record lineage. Use `bridge.assistant.BridgeAssistant` for all data (same operations the MCP server exposes). FastAPI + server-rendered HTML or a single static page; no external CDN assets. CLI: `python -m bridge --run-db ... web --port 8710`.

### T-108 · Second source profile for drift testing · `done`
Files: `testbed/halcyon/profiles/`, small hooks in `testbed/halcyon/generator.py` (`Config.rates`, `vocab.FACILITIES`)
A "Lakeside facility" profile: metric units, different visit codes, different sig style, so the drift monitors have something to catch mid-run.

### T-109 · Answer-key scoring harness · `done`
Files: `testbed/scoring.py` (new), `tests/testbed/test_scoring.py`
Given a Halcyon export dir and a Bridge run DB, report for every planted issue type in `answer_key/issues.jsonl` how many were *surfaced* by Bridge (a question linked to the record, a lossy fidelity annotation on it, or a dropped/superseded/held status), and identity accuracy (`answer_key/persons.json` vs Bridge's `xref` kind `pat`: pairwise precision/recall). Read the run DB with plain `sqlite3` (tables documented in `src/bridge/runs/store.py`) — `testbed/` must not import `bridge`. Output JSON + a short Markdown table. Acceptance: tests generate a small export, run Bridge via the fixtures pattern in `tests/bridge/conftest.py`, and assert the report has an entry for every issue type.

### T-110 · Performance at 50k patients · `done`
Files: `tools/bench.py`, `.github/workflows/t110-50k.yml`, `src/bridge/runs/`, `src/bridge/monitor/rules.py`, `src/nimbus/service.py`
Goal was a verified 50,000-patient end-to-end conversion with identical behavior. Outcome (#31): a full 50k run on GitHub's
`ubuntu-latest` completed with all 4.82M records terminal and verification OK in 29.9 min (35.9 ms/patient; 29.0 at 2k,
29.8 at 10k), peak RSS 2.1 GB. Main fixes: indexed work queue and dependent wakeups, UUIDv7 Nimbus ids, buffered/bulk
SQLite writes, incremental drift baselines, primary-key blocked-record release, filtered verification scans. Conversion
output is byte-identical to the pre-optimization code at equal batch size. PRs run 100-1000 patients; 2k-10k runs weekly
and on dispatch (with a per-patient growth guard); 50k is dispatch-only with a 45-minute cap.

### T-111 · Export mutator for cutover testing · `done`
Files: `testbed/halcyon/mutate.py` (new), CLI `python -m testbed.halcyon mutate --from <exportA> --out <exportB> --seed N`, `tests/testbed/test_mutate.py`
Produce export B from export A as "the same system some weeks later": keep every existing primary key stable; add new patients (with charts), new visits/labs/notes for existing patients, demographic changes on ~5% of patients (also emitted as ADT A08 in B's feeds), status changes (meds discontinued, appointments completed/cancelled), and delete a small number of rows (e.g. entered-in-error problems, cancelled-and-purged appointments). Copy feeds/extracts and append new messages. Write `answer_key/delta.json` listing every added/changed/deleted key by table. Do not import `bridge` or `nimbus`. Acceptance: deterministic for a seed; tests assert keys in A remain stable in B except listed deletions, and that delta.json is complete (diff A vs B tables equals delta.json).

### T-112 · Sentence-style sigs (Lakeside) · `done`
Files: `src/bridge/normalize/sig.py`, `tests/bridge/test_sig.py`
The Lakeside profile (`testbed/halcyon/profiles/lakeside.py`, `LAKESIDE_SIGS`) writes sigs as full sentences ("Take 1 tablet by mouth every 4 to 6 hours as needed for wheezing", "Inject 10 units under the skin at bedtime"). Today ~45% of Lakeside sigs fall back to text (see `python -m testbed.halcyon generate --profile lakeside` then a Bridge run's `loss` report: `MedicationRequest dosage degraded`). Extend the parser to handle spelled-out frequencies/intervals/ranges ("every 4 to 6 hours", "three times a day", "for 10 days", "as needed for X", "under the skin", "inhale"), keeping the T-102 contract (ranges lower confidence). Acceptance: every sig in `LAKESIDE_SIGS` and `vocab.FORMULARY` parametrized in tests with expected fields; no regressions in existing tests.

### T-113 · Second test source EHR (Delphi): testbed and estate · `done`
Files: `testbed/delphi/` (new, incl. `analysts/`), `docs/delphi.md` (new), tests
A second synthetic legacy source system, added as an alternative to Halcyon: fixed-width text extracts with a shipped layout file (no database, no HL7), an event journal as the change feed, two-digit years with a pivot year of 30, Julian dates in the lab file, per-department patient account numbers with no master patient index, free-text diagnoses with a shorthand dictionary, medications by NDC, and lab results as value+flag strings. The generator is event-sourced and deterministic per seed, and writes `answer_key/` in the Halcyon schema so `testbed/scoring.py` works unchanged. Scope is the testbed plus its documentary estate: the export ships the vendor's data dictionary (`DATADICT.TXT`, version 4.1 against layout version 5.0), which is deliberately fallible (undocumented fields, stale and wrong entries); every deliberate discrepancy between the estate's documents and the generated data is recorded in `answer_key/estate_discrepancies.json`. `testbed/delphi/analysts/` holds four analyst knowledge profiles (registration, laboratory, pharmacy, systems) — self-contained interview briefs, including points where the analysts disagree with each other. Bridge does not read Delphi in this task: a Bridge import for Delphi is to be generated later by the interview-driven (Socratic) import builder, working from the estate and the analyst profiles. Acceptance: full pytest green; layout round-trip tests; determinism (digest-pinned) tests; estate tests (dictionary ships and parses, ledger matches the dictionary's planted errors, analyst profiles present and complete).

### T-115 · Socratic import builder: design and board · `review`
Files: `docs/socratic-import-builder.md` (new), `TASKS.md`
Design for the interview-driven import builder (see the doc): Bridge learns a new source system from its documentary estate (manuals, a fallible data dictionary, sample extracts) plus structured interviews with analysts, and generates the import spec (profile, crosswalks, reader binding) with provenance for every fact. Decisions recorded in the doc: package `src/bridge/interview`; ledgers committed at `src/bridge/interview/ledgers/<source>.jsonl`; Halcyon re-derivation (T-120) is a REQUIRED acceptance case, not an optional experiment. This task also adds board entries T-115..T-120. (Numbering starts at T-115 because T-114 was already used by a Pages helper task.) Acceptance: design doc merged; board entries present.

### T-116 · Socratic core: profiler, claim store, coverage, ledger · `review`
Files: `src/bridge/interview/{__init__,profiler,claims,coverage,ledger}.py` (new), `tests/bridge/test_interview_core.py` (new)
Deterministic core of the Socratic import builder. Profiler reads CSV exports (headers) and fixed-width exports given a shipped layout (e.g. Delphi `LAYOUTS.DAT`) and emits observations only (record counts, blank rates, distinct counts, numeric ranges, date-shape parse rates, flag-suffix rates, truncation piles) — never conclusions. Claim store holds `(subject, predicate, value, source, confidence)`; a source dictionary ingests as claims; conflicting values on the same subject/predicate become first-class Dispute objects. Coverage checklist derives from the import-spec schema (every file needs a layout binding; every field a type/convention decision; identity a keying story; every code set a crosswalk or a documented gap). Ledger is append-only JSONL with stable sequential event ids. Bridge reads estate files only; never the answer key, never a generator. Acceptance: unit tests for all four modules incl. a Delphi fixed-width fixture; full pytest green.

### T-117 · Socratic analyst interface over MCP · `review`
Files: `src/bridge/interview/analyst_server.py` (new), `src/bridge/interview/analysts.py` (new), `tests/bridge/test_interview_analysts.py` (new)
An MCP server (following `src/bridge/mcp_server.py` patterns) exposing `ask(analyst, question)` and `read_estate(document)`. `read_estate` enforces a path allowlist: estate documents and analyst profiles only — no answer key, no generator code, no path traversal. Backends: a stub backend that answers deterministically from recorded Q&A data plus each profile's stated blind spots (replying "outside my area" outside them), and a profile-primed prompt builder for a future live LLM backend (not exercised in tests). Firewall (post-merge review, PR #38): analyst profiles are the backend's private knowledge — they are NOT in the `read_estate` allowlist, and the builder reaches analysts only through `ask`. No live LLM calls anywhere in tests. Acceptance: replay tests — a recorded ledger's questions put to the stub backend return the recorded answers byte-for-byte; allowlist tests incl. traversal attempts; full pytest green.

### T-118 · Spec generator and extract dispatch · `review`
Files: `src/bridge/interview/specgen.py` (new), `src/bridge/interview/reader.py` (new), `src/bridge/extract/registry.py` (new), `src/bridge/runs/runner.py` (dispatch only), `tests/bridge/test_interview_specgen.py` (new)
`generate_spec(ledger, claims, source)` is a pure function whose PRIMARY output is a declarative spec (JSON): rules each carrying provenance (dictionary | analyst | profiler-data) and a `data_confirmed` flag. A profile module in the existing profile shape is rendered thinly from that JSON (not the other way round), plus crosswalk CSV text with citation columns and a reader binding. Safety rule: identity merges always route to a human reconciliation question in the generated spec, never an auto-merge rule, even when an analyst calls merges routine — specgen enforces this over any contrary claim, with a test. Same ledger in, byte-identical spec out. The runner's hardwired Halcyon extract call generalizes into a reader registry keyed by the spec/profile; Halcyon's existing path stays the default control, unchanged in behavior. A generic fixed-width reader stages records from a binding. Acceptance: determinism test (generate twice, compare bytes); a small seeded Delphi export stages records end-to-end through the generated spec in tests; existing pipeline tests unchanged and green.

### T-119 · First Delphi interview and discrepancy scorecard · `review`
Files: `src/bridge/interview/ledgers/delphi.jsonl` (new), `src/bridge/interview/specs/delphi/` (generated, committed), `src/bridge/interview/scorecard.py` (new), `docs/delphi-scorecard.md` (generated report), `tests/bridge/test_interview_delphi.py` (new)
Author the recorded Delphi interview: profiler observations over a seeded export plus stub-analyst Q&A working the coverage checklist against the Delphi estate (dictionary v4.1 vs layouts v5.0). Generate the Delphi spec from the ledger and commit both. The scorecard grades every entry in the Delphi grading ledger — the nine dictionary discrepancies plus the analyst-belief and disagreement entries added after the PR #38 review (16 total) (`estate_discrepancies.json`, read by tests/report tooling only — never by Bridge code) as caught-by-profiling / caught-by-analyst / swallowed / routed-to-runtime-question. Verdicts are computed from ledger + spec data; the discrepancy-to-subject mapping may be explicit data in the scorecard module, the verdicts may not be hardcoded. Acceptance: scorecard test asserts a computed verdict per discrepancy and that the spec's known-unknowns match the routed set; report committed; full pytest green.

### T-120 · Halcyon estate and re-derivation (required acceptance case) · `review`
Files: `testbed/halcyon/estate/` (new), `testbed/halcyon/analysts/` (new), Halcyon grading ledger in the export answer key (`estate_discrepancies.json`, written by `testbed/halcyon/estate` tooling/fixtures), `src/bridge/interview/ledgers/halcyon.jsonl` (new), `src/bridge/interview/specs/halcyon/` (generated, committed), `src/bridge/interview/diff.py` (new), `docs/halcyon-rederivation.md` (generated report), `tests/bridge/test_interview_halcyon.py` + `tests/testbed/test_halcyon_estate.py` (new)
Halcyon currently has no estate: its import was hand-written omnisciently. Build one: in-universe dictionary excerpts and interface/site notes with some information missing and some inconsistent, four analyst profiles (HIM/registration, lab, pharmacy, interface engineer) with blind spots and at least two genuine disagreements and no planted-issue language, and a grading ledger of the estate's deliberate discrepancies. Then run the builder on it: a recorded Halcyon ledger, a generated Halcyon spec, and a diff/score report against the hand-written `src/bridge/profiles/halcyon.py` on a defined fact subset (system org, MRN scheme, facility timezones, vital units per facility, charge-cents cutover, lab-feed-only window) plus a crosswalk-coverage comparison. Facts the process could not establish must appear in the diff honestly as disputed or missed. The generated spec is a parallel artifact; the hand-written profile remains the default control in this pass. Acceptance: estate tests (profiles complete, disagreements present, no answer-key leakage into estate text); diff test computes matched/disputed/missed from the artifacts; report committed; full pytest green.

### T-121 · Structured keying story and observation bindings on claims · `review`
Files: `src/bridge/interview/specgen.py`, `src/bridge/interview/claims.py`, `src/bridge/interview/ledgers/*.jsonl` (re-pinned if the format changes), `tests/bridge/test_interview_specgen.py`, `tests/bridge/test_interview_acceptance.py`
Follow-up from the PR #42 round-3 review (optional, not blocking). Two honesty gaps in specgen: (1) the identity `keying_story` is free text screened by a merge-language regex that catches only the phrasings it lists ("link any two charts sharing SSN4+DOB without review" and "collapse duplicates on SSN4+DOB automatically" both pass unflagged today; the runtime stays safe via the Runner's MERGE_POLICY check, so this is about the spec's honesty) — make the keying story a structured value (key fields, no action verb) so there is nowhere for an instruction to hide; (2) `OBSERVATION_SUBJECT_FIELDS` hard-codes Delphi file names (`REG.TXT.DOB`, `LABDICT.TXT.UNIT`) into the generic generator, so a non-`field:` subject from another source (e.g. Halcyon's `pivot_year`) can never be data-confirmed — record the subject-to-field binding on the ledger observation or the claim instead of in generator code. Acceptance: the two regex-evading phrasings are structurally impossible or flagged; a Halcyon-shaped non-field subject can be data-confirmed from a recorded binding; committed specs re-pinned with their diffs explained; full pytest green.
