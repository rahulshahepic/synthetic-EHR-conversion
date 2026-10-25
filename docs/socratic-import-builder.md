# Design: the Socratic import builder

Status: approved design (owner decisions recorded below). Implemented by
tasks T-115..T-120.

## Problem

Bridge's Halcyon import was authored with the generator's source open on the
other screen. The profile module describes itself as "facts the conversion team
learned from the source system's documentation and site interviews," but the
team was omniscient: per-facility units, the charge-cents cutover, and every
crosswalk were written from ground truth. Real conversion work has no ground
truth. It has a fallible data dictionary, sample data, and people.

This design makes import authoring an evidence process instead of an act of
authorship. Bridge gains a subsystem that *discovers* an import spec for a new
source by profiling its extracts and interviewing its analysts, and emits the
spec with provenance for every fact. Delphi (T-113) is the first subject: it
ships data, a deliberately fallible dictionary, four analyst profiles, and a
private grading ledger of the estate's nine discrepancies to grade the process
against. Halcyon re-derivation (T-120) is the second, required acceptance
case: the builder must re-derive the Halcyon import from an estate built for
it (T-120) and be diffed against the hand-written import, which stays in
place as the control.

## Decisions (owner, Oct 25, 2026)

1. **Package name:** `src/bridge/interview`. Feature name: the Socratic
   import builder. (The method's technical name is maieutics; the repo
   keeps the plain name.)
2. **Ledgers live in the repo**, committed at
   `src/bridge/interview/ledgers/<source>.jsonl`, beside the generated
   specs they produced. Provenance you cannot re-read is not provenance.
3. **Halcyon re-derivation is required, not an experiment.** It is the
   acceptance case that proves the builder works on a source whose truth
   the team already knows — because that is the only way to measure what
   the honest process misses. The hand-written Halcyon import remains the
   default control; the generated spec is a parallel artifact with a
   measured diff (T-120).

Task numbering starts at T-115 because T-114 was already used by a GitHub
Pages helper task.

## Principles

1. **Everything the builder believes is a claim with provenance.** A claim
   cites a dictionary section, a profiler observation, or a ledgered analyst
   answer, plus a confidence. Unsourced facts cannot enter the spec.
2. **The builder never sees the generator.** Its inputs are the estate: the
   export files, the shipped dictionary and manuals, and the analyst profiles.
   The answer key stays where it has always been: out of Bridge's reach
   (`tests/test_boundaries.py` enforces this for all of `src/bridge`).
3. **Uncertainty routes to runtime, not to guesses.** Unresolved claims become
   monitor thresholds and reconciliation questions in the generated spec, the
   same machinery a run already uses for records it cannot decide.
4. **The interview is data.** The process produces an append-only ledger.
   Spec generation from a ledger is a pure function, so CI replays recorded
   ledgers through stub analysts and never runs a live interview.

## Components

### 1. Profiler — `src/bridge/interview/profiler.py`

Reads an export directory and the source's layout/dictionary artifacts and
emits a `ProfileReport` (JSON-able dict): per-file record counts and widths;
per-field character classes, blank rates, distinct counts and samples;
numeric ranges; date-shape detection (which fields parse as YYMMDD, Julian,
or timestamp, and at what rates); value-plus-flag suffix rates; suspected
truncations (values piled at maximum width). The report states observations,
never conclusions: "REG.DOB parses as YYMMDD for 99.2% of rows" is an
observation; the pivot year is a question.

### 2. Claim store — `src/bridge/interview/claims.py`

A claim is `(subject, predicate, value, source, confidence)` where source is
a dictionary reference, a profiler observation id, or a ledger entry id.
The dictionary is ingested as claims at its stated version, so version skew
is visible from the start. Two claims on the same subject/predicate with
different values form a *dispute*, a first-class object with a resolution
state, not an overwrite.

### 3. Coverage checklist — `src/bridge/interview/coverage.py`

Derived from the import spec's schema: every file needs a layout binding;
every field needs a type, a date/unit/code convention or an explicit
"pass through as text" decision; identity needs a keying story; every code
set needs a crosswalk or a documented gap. The checklist is what the
interviewer works through; an unchecked item at spec time becomes a runtime
question or a monitor, never a silent default.

### 4. Analyst interface (MCP) — `src/bridge/interview/analyst_server.py`

An MCP server exposing two tools: `ask(analyst, question)` and
`read_estate(document)`. `read_estate` serves only estate documents
(manuals, dictionaries, layouts, sample extracts) under a path allowlist,
which is the firewall made mechanical. **Analyst profiles are never in
the allowlist.** The builder reaches analysts only through `ask`: a
profile is the analyst backend's private knowledge, loaded by the
simulator, and the interviewer never reads one directly. (The repo's
AGENTS.md states the same rule for agents working in this repo.)
Three analyst backends:

- **Simulated (LLM):** a session primed with exactly one analyst profile
  (`testbed/<source>/analysts/<name>.md`) and the estate documents that
  analyst could plausibly have. It knows nothing else; in particular it has
  never heard of planted issues, seeds, or answer keys. (Not used in tests.)
- **Stub (CI):** a deterministic lookup over recorded question/answer pairs,
  with the profile's stated blind spots returning "outside my area" verbatim.
  Extends the precedent of `testbed/simulated_user.py`, which already plays
  analyst for runtime reconciliation.
- **Human:** the M12 elicitation path in `bridge/mcp_server.py`, for the day
  a real analyst sits for an interview.

### 5. Interviewer

Deliberately not a Bridge module. The interviewer is any LLM (or person)
driving the tools above through a session: work the checklist, consult claims
and the profile report, file questions where a decision depends on a missing
or disputed claim, and record resolutions. Bridge provides the state (claims,
checklist, ledger) and the instruments; the judgment is the interviewer's,
the same way the reconciliation assistant already works at runtime.

### 6. Ledger — `src/bridge/interview/ledgers/<source>.jsonl`

Append-only record of one import's discovery: observations imported from the
profiler, questions asked (to whom, why, which checklist item), answers,
claims asserted and retracted, disputes and how they resolved. Event ids are
stable and sequential (`E000001`, ...). The ledger is committed alongside
the generated spec and is the artifact of record for "how do we know this."
It is also the CI fixture format.

### 7. Spec generator — `src/bridge/interview/specgen.py`

A pure function from ledger + claims to the import spec package. The
**primary output is a declarative spec (JSON)**: a list of rules, each
carrying its provenance — `dictionary`, `analyst`, or `profiler-data`,
with a reference — and a `data_confirmed` flag that is true only when
the profiler's observations (or a dispute resolution citing them through
structured evidence refs) back the rule *and are about the rule's
subject*: a `field:` subject must match the observation's file and field
exactly, and other subjects carry an explicit subject-to-field mapping.
An observation about some other field confirms nothing. The JSON spec
is the artifact of record. On top of it:

- A profile module in the existing profile shape (compare
  `src/bridge/profiles/halcyon.py`), rendered thinly from the JSON spec,
  every constant carrying a provenance comment
  (e.g. `# ledger:E000017 (Marla Denny, registration)`).
- Crosswalk CSV text with citation columns.
- A reader binding (layouts, channel semantics) consumed by the extract
  stage, as a JSON-able dict.

One rule the generator applies regardless of what any claim says:
**identity merges route to a human reconciliation question, never to an
auto-merge rule** — even when an analyst describes merging as routine.
Analyst confidence is evidence about facts, not a safety policy.

Generated packages are committed under `src/bridge/interview/specs/<source>/`
so a generated profile never silently replaces a hand-written one. Same
ledger in, byte-identical spec out (tested). Disputes left unresolved at
generation time are emitted as spec-level questions, listed in a
"known unknowns" section of the generated profile.

### 8. Runner dispatch

The one hardwired spot in the current code: `runs/runner.py` imports
`HalcyonExport` and `stage_all` directly while the profile is a parameter.
The builder's arrival generalizes extract the same way: readers register by
name in `src/bridge/extract/registry.py`, the spec/profile names its reader,
and the runner dispatches. Halcyon's hand-written path stays the default
control, behavior unchanged.

## Grading the interviews

**Delphi (T-119).** The export's grading ledger lists nine planted
discrepancies, each with a "how to check." The scorecard
(`src/bridge/interview/scorecard.py`) grades each one — caught by profiling,
caught by an analyst, swallowed into the spec as truth, or routed to a
runtime question — computed from the ledger and the generated spec. The
discrepancy-to-claim-subject mapping is explicit data; the verdicts are
computed, never hardcoded. Bridge code never reads the grading ledger; tests
and report tooling hand it in as data.

**Halcyon (T-120, required).** Halcyon gets an estate of its own
(dictionary excerpts, interface/site notes — some information missing, some
inconsistent — and four analyst profiles), a recorded interview, a generated
spec, and a diff report against the hand-written profile on a defined fact
subset: system org, MRN scheme, facility timezones, vital units per
facility, the charge-cents cutover, the lab-feed-only window, plus a
crosswalk-coverage comparison. Facts the honest process could not establish
appear in the diff as disputed or missed. That diff is the measured price of
honesty, and the thing this whole apparatus exists to shrink.

## Testing without live interviews

- Profiler, claim store, coverage, and specgen are deterministic units with
  ordinary pytest coverage on small seeded exports.
- Analyst behavior in CI is the stub backend over recorded ledgers: replaying
  a ledger's questions returns the recorded answers byte-for-byte.
- No live LLM calls anywhere in tests. Ever.

## Task breakdown

- **T-115** — this design and the board entries.
- **T-116** — profiler + claim store + coverage checklist + ledger
  (deterministic core).
- **T-117** — MCP analyst server, stub backend, recorded-ledger replay tests.
- **T-118** — spec generator + runner extract dispatch. Halcyon control
  unchanged.
- **T-119** — first Delphi interview: recorded ledger, generated spec,
  discrepancy scorecard.
- **T-120** — Halcyon estate + re-derivation: REQUIRED acceptance case,
  diffed against the hand-written import.
