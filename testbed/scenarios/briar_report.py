"""Human-readable results from executed evidence, not static success claims."""
from __future__ import annotations

import html
import json
from pathlib import Path


def build(root: Path) -> str:
    load = lambda name: json.loads((root / name).read_text())
    results = load("corrected_results.json")
    grades = load("grade_summary.json")
    native = load("native_result.json")
    manifest = load("source/manifest.json")
    evidence = load("evidence.json")
    population = manifest["counts"]["REG"]
    by_type = results["summary"]["by_type"]
    note_count = sum(by_type["DocumentReference"]["counts"].values())
    note_loaded = results["target_counts"]["DocumentReference"]
    logical_allergies = sum(by_type["AllergyIntolerance"]["counts"].values())
    native_note_loss = native["leading_note_whitespace_stripped"]
    appt_held = by_type["Appointment"]["counts"].get("held", 0)
    physical_outcomes = results["accounting_dispositions"]
    records = load("corrected_records.json")
    withdrawn = sum(r["status"] == "dropped" and "withdraws" in (r["note"] or "") for r in records["Observation"])
    missing = by_type["Observation"]["counts"].get("dropped", 0) - withdrawn
    rerun_rows = [["Initial corrected run", population, "End-to-end conversion", f"{sum(results['target_counts'].values()):,} loaded, zero rejected, full read-back and field/disposition grading pass"]]
    for label, title, purpose in [("replay", "Fresh target, batch size 37", "Batch-order/replay sensitivity"), ("idempotent", "Same target, repeat import", "Idempotency")]:
        if (root / (label + "_results.json")).exists():
            rerun_rows.append([title, population, purpose, "Same clinical content and outcomes" + ("; no new duplicate records" if label == "idempotent" else "")])
    if (root / "second_population/corrected_results.json").exists():
        second = load("second_population/corrected_results.json")
        second_pop = load("second_population/source/manifest.json")["counts"]["REG"]
        rerun_rows.append(["Second population, new seed", second_pop, "Reuse the same discovered 3.7 spec", f"{sum(second['target_counts'].values()):,} loaded; verification and field/disposition grading pass"])
    rerun_table = "| Run | Population | Purpose | Actual result |\n|---|---:|---|---|\n" + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in rerun_rows)
    rows = []
    for rt, entry in sorted(results["summary"]["by_type"].items()):
        c = entry["counts"]
        rows.append([rt, sum(c.values()), c.get("loaded", 0), c.get("held", 0), c.get("blocked", 0), c.get("dropped", 0), c.get("rejected", 0)])
    totals = [sum(r[i] for r in rows) for i in range(1, 7)]
    rows.append(["Total", *totals])
    table = "| Resource | Logical records | Loaded | Held | Blocked | Dropped | Rejected |\n|---|---:|---:|---:|---:|---:|---:|\n" + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in rows)
    text = f"""# Briar EHR conversion dress rehearsal — October 26, 2026

The autonomous rehearsal is complete. The explicitly authored source adapter loaded **{totals[1]:,} resources across nine types** in **{results['seconds']:.3f} seconds**, with **{totals[5]} target rejections**. Every one of **{results['physical_rows']:,} physical export rows** is accounted for. **{sum(g['checks_total'] for g in grades):,} clinical-field, identity, target-presence and disposition assertions** passed across {len(grades)} executed runs, listed below. These assertions are not independent tests or independent clinical validation.

**Operational result: completed with exceptions. Go-live result: NO-GO.** {totals[2]} records are held for unresolved source evidence, {totals[3]} depend on held records, and {totals[4]} observations are intentionally not loaded (withdrawn accessions or explicit no-result sentinels). No sign-offs were invented and no patients were merged. A deferred question is not a clinical answer and cannot release or drop its held records.

## What was actually built and executed

Briar is a new synthetic source, separate from Halcyon and Delphi: {population} registration charts at two formerly separate installations, fixed-width departmental files, local chart numbers, revisioned labs, a withdrawal journal, note continuations, medications, diagnoses, appointments and charges. Its 2018 dictionary is mostly right but contradicts a 2026 support note and several operational workflows. Five named simulated analysts have different knowledge and blind spots. There are 15 discovery questions and {len(load('corrected_runtime_interviews.json'))} runtime follow-ups in the evidence.

The stock Socratic builder generated a 91-rule declarative spec, provenance ledger, reader binding, Python profile and crosswalk CSVs. **The stock generated-reader path staged {sum(sum(c.values()) for c in native['counts'].values()):,} source rows and loaded zero patients.** Its run correctly remains `staged`; the current implementation does not generate source-to-Nimbus domain mappers. I wrote an explicit test-scenario adapter using the discovered spec, then ran the ordinary Bridge Runner and embedded Nimbus **HTTP API contract**, including target validation, dependency checks, fidelity annotations, questions, counts, clinical sentinels and full loaded-record read-back. This was local embedded HTTP transport, not a remote-server/network test.

## The consequential disagreements

| Claim or conflict | What was checked | Conversion decision |
|---|---|---|
| Dictionary and systems: CHART is enterprise-wide. Registration: site-local. | {population} registrations, only {evidence['cross_site_chart_collisions']} distinct CHART values; separate source installations; systems withdraws old assertion. | SITE+CHART identifies source charts; cross-site records remain separate. Matching demographics produce an identity-review question, never an automatic merge. |
| Systems uses a 1950 DOB pivot; registration proposes 1930. Dictionary says six-digit DOB. | {evidence['dob_lengths'].get('8',0)} eight-digit dates, {evidence['dob_lengths'].get('0',0)} blanks and {evidence['dob_lengths'].get('6',0)} six-digit dates. No chart evidence for the legacy century. | Parse valid YYYYMMDD only. Hold all {by_type['Patient']['counts'].get('held',0)} uncertain birth dates; dependent resources wait. Neither analyst's preferred pivot becomes truth. |
| Lab supervisor: all Outreach glucose is now mmol/L; ignore unit labels. | B-site glucose rows still explicitly carry mg/dL, alongside mmol/L. These counts include historical revisions. Supervisor acknowledges residual devices. | Preserve transmitted units. Missing glucose units are held. No magnitude-based or site-wide unit conversion. |
| Dictionary: MED H is historical and may be skipped. Pharmacy: current H is on hold. | Pharmacy confirms the changed 3.7 workflow and refuses to attest to older versions. | Preserve current on-hold therapy; adapter rejects other delivery versions. Unmapped MISC drugs remain held with original name and sig archived. |
| Dictionary: all amounts are cents. Billing: Outreach changed to dollars. | A cents, B pre-cutover cents and B post-cutover decimal dollars all occur. Billing confirms service date, not extraction date, controls the change. | Preserve $125.50 across all three regimes. Quarantine credits rather than invert their signs. |
| NKA Y conflicts with positive allergy text. | {evidence['nka_positive_conflicts']} source conflicts; registration explains a sticky NKA flag. | Retain positive allergies and clear contradictory NKA on loaded patients. Allergies whose patients have unknown DOB remain blocked. |
| Numeric-only labs versus NEG, 999999 and comparator results. | Domain owner distinguishes a valid culture result, a missing-value sentinel and >600H-style measurements. | Preserve negative cultures, comparators and flags. Do not create a numeric 999999 observation. |
| Latest physical lab row versus latest revision; potassium delete versus entire accession. | Revision order is reversed; source journal and owner define whole-accession withdrawal. | Highest numeric revision wins. Withdraw every test on the accession; never resurrect its older revision. |
| APPT R means rescheduled versus possibly arrived. | No scheduling owner or status audit is available. | All {appt_held} R appointments stay held. A convenient guess does not become a status map. |
| Full-width notes imply truncation. | Follow-up distinguishes continuation segments from upstream truncation; no original-length marker exists. | Reassemble by numeric SEQ, preserve indentation and delivered text; mark original completeness unverified. |
| Local times include 2400, 2461 and DST transition hours. | Both sites are Chicago local; support note defines midnight rollover but cannot establish DST offsets. | Normalize documented 2400 to next midnight; hold invalid, repeated and nonexistent wall-clock times. |

## Record accounting

{table}

Physical rows and logical resources are different counts: {physical_outcomes.get('superseded_revision_archived',0)} earlier glucose revisions are retained in the source archive, {manifest['counts']['NOTE']} note segments assemble into {note_count} documents, {manifest['counts']['JRN']} journal rows withdraw accessions, and {logical_allergies} registration rows also yield an allergy resource. The per-file/per-line accounting file links every physical row to its disposition and logical target. The {by_type['Observation']['counts'].get('dropped',0)} dropped observations comprise {withdrawn} withdrawn tests and {missing} no-result sentinels after withdrawal precedence. None are silently discarded as unparsed input.

## Verification and repeated runs

{rerun_table}

The stock verifier's default sentinels still depend on Halcyon-shaped source fields. The scenario adapter provides those explicit normalized aliases, and the separate source-specific grader checks actual Nimbus API snapshots for every logical record, every loaded patient's identity reference, dates, quantitative and qualitative results, revisions, comparators, units, flags, medication status and sig, diagnosis coding/text, allergy text, note bytes/order and charge scaling. This is stronger than checking only that a record was accepted, but it does not measure source capabilities absent from this fixture.

The discovery ledger replays to byte-identical spec/profile output, all analyst answers replay exactly, and re-profiling reproduces the recorded observations. A test also forbids grading-file reads during discovery and conversion. Seven fault-injection tests demonstrate that the grader rejects wrong units, lost comparators, stripped note indentation, active/on-hold swaps, wrong charge scaling, invented diagnosis coding and extra target records.

## Failures found during the rehearsal

1. **Native builder stops at staging.** Source-file bindings are working; general source-to-domain mapping and execution of generated semantic rules/known-unknowns are still missing. The explicit adapter is a demonstrated workaround, not evidence that the builder generated a complete ingestion.
2. **Generic fixed-width reader strips leading clinical whitespace.** `src/bridge/interview/reader.py:126` calls `.strip()` on every field. All {native_note_loss} indented note continuations lose their indentation on the native path. The scenario reconstructs note content using the generated field spans and trims only right padding; all {note_loaded} loaded notes match the delivered segments exactly. Production reader behavior is unchanged by this PR.
3. **Read-back compares timestamp spellings literally.** `src/bridge/verify.py:37` considers equivalent UTC `+00:00` and `Z` strings unequal. The first adapter attempt was stopped with read-back alerts; a captured example confirms the instant did not change. The adapter now emits Nimbus's canonical UTC `Z` representation. The original failed-attempt log is preserved separately; no alert was waived to force a pass.

These findings should become product work: generate/validate domain mappings and enforce known-unknown routing; support per-field whitespace semantics; compare typed timestamps semantically; make clinical sentinel definitions source-specific. Unavailable clinical facts remain a source-operations problem, not something a converter can safely invent.

## What remains unresolved

There are {results['summary']['open_questions']['blocking']} blocking question groups covering missing/ambiguous DOB, invalid/DST times, unverified glucose units, unmapped medications, source credits and APPT R. A nonblocking identity group covers two charts with matching demographics, retained separately. Runtime follow-up questions were sent through the same simulated-analyst ask interface; without additional chart evidence, those answers stay unknown and release no records. Fidelity losses or explicitly unverified assumptions also await owner sign-off. The run's NO-GO is intentional and supported by the unresolved records, not a stopped or unfinished execution.

## Limits of this evidence

The same assistant authored the source fixture, analysts, interview and adapter. This is **not a blinded test** of discovery, and its success rate is not an independent estimate of real-world import quality. Analysts use deterministic recorded answers through `AnalystService.ask`, not independent live models or actual staff. Grading truth is kept out of the conversion code path and consulted only by the separate scoring step after snapshots are written, but the fixture author already knows what was planted. A genuinely blinded follow-up needs an independently authored estate and independently supplied analyst backend. The second population changes the seed and size, not the source's underlying error families. The scenario preserves source charge-to-visit references but does not validate service-date consistency against encounter dates; source-era billing dates therefore need a separate revenue-cycle audit. No claim is made about production scale, network faults, live incremental cutover, real clinical terminology validity or real-world go-live readiness.

## Reproduce

Tested base: `8175d7eb0026012e7174121b35e2a15b6a76e6e4` plus this task branch. Python 3.12; existing project dependencies; no added dependency or remote LLM calls.

```bash
python -m pip install -e '.[dev]'
python -m testbed.scenarios.briar --out runs/briar-new --patients 320 --seed 2626
python -m pytest -q
```

The output contains source files and private grading truth, frozen discovery and full runtime ledgers, generated spec/profile/binding/crosswalks, per-field profiling evidence, source-row accounting, target API snapshots, record outcomes, read-back/readiness reports, HTML reports, SHA-256 evidence hashes, repeated-run comparisons and computed grades. Output directories must be fresh; prior evidence is never overwritten.
"""
    (root / "RESULTS.md").write_text(text)
    # Standalone HTML with all the interview text and machine results embedded.
    htmlrows = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    interview = (root / "INTERVIEW.md").read_text()
    runtime = load("corrected_runtime_interviews.json")
    details = "".join(f"<details><summary>{html.escape(q['kind'])} · {q['affected']} records</summary><p>{html.escape(q['response']['answer'])}</p><p>Disposition: left open; no verified value supplied.</p></details>" for q in runtime)
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Briar conversion rehearsal</title>
<style>body{{font:17px/1.6 system-ui,sans-serif;color:#202b2b;background:#f5f2eb;margin:0}}main{{max-width:1050px;margin:auto;padding:36px 24px}}h1{{font:42px/1.12 Georgia,serif;max-width:700px}}h2{{font:27px Georgia,serif;margin-top:36px}}.metrics{{display:flex;flex-wrap:wrap;gap:12px}}.metrics div{{flex:1;min-width:140px;background:white;padding:16px;border-top:4px solid #315d50}}b.big{{display:block;font-size:30px}}.decision{{border-left:5px solid #9b492d;background:#fff4e7;padding:16px}}table{{border-collapse:collapse;background:white;width:100%;font-size:14px}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #dedcd6}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px;font:14px/1.6 ui-monospace,monospace}}details{{background:#fff;padding:12px 16px;margin:8px 0}}summary{{cursor:pointer;font-weight:650}}a{{color:#195b4a}}.table{{overflow:auto}}small{{color:#59635f}}</style>
<main><small>SYNTHETIC EHR / OCTOBER 26, 2026</small><h1>A messy source. A completed rehearsal. An honest NO-GO.</h1>
<p>Briar Community EHR: two sites, fallible documentation, five disagreeing analyst roles, revisioned results and unresolved clinical facts.</p>
<div class="metrics"><div><b class="big">{results['physical_rows']:,}</b>source rows accounted</div><div><b class="big">{totals[1]:,}</b>resources loaded</div><div><b class="big">{totals[5]}</b>target rejections</div><div><b class="big">{results['seconds']:.2f}s</b>first corrected conversion</div></div>
<p class="decision"><strong>Conversion completed with exceptions. Go-live: NO-GO.</strong><br>{totals[2]} held records, {totals[3]} blocked dependencies, unresolved source evidence and unsigned fidelity losses. No invented birth dates, patient merges or human approvals.</p>
<h2>The product finding</h2><p>The generated spec stages the source. It does not yet generate the domain mappers needed to finish the conversion. An explicitly authored adapter completed this run through Bridge and the Nimbus API. The generic reader also strips note indentation, and timestamp read-back needs canonical spelling. Both workarounds are disclosed.</p>
<h2>Record accounting</h2><div class="table"><table><thead><tr>{''.join('<th>'+c+'</th>' for c in ['Resource','Logical','Loaded','Held','Blocked','Dropped','Rejected'])}</tr></thead><tbody>{htmlrows}</tbody></table></div>
<h2>Evidence strength</h2><p>{sum(g['checks_total'] for g in grades):,} field/disposition assertions passed across {len(grades)} runs. The repeated-run details and population sizes are recorded in the complete report. Seven fault injections demonstrate that clinically wrong output fails scoring.</p>
<p><strong>This was not blinded.</strong> One assistant authored the fixture, analyst answers and adapter. Analyst answers are deterministic stubs. Conversion never reads grading truth, but its author knows the planted cases. Results support this rehearsal, not a general real-world success rate.</p>
<h2>Discovery conversation</h2><details><summary>Read all 15 discovery questions, analyst answers and resolutions</summary><pre>{html.escape(interview)}</pre></details>
<h2>Runtime analyst follow-up</h2>{details}
<h2>Complete report</h2><details><summary>Methods, contradictions, product failures, limits and reproduction</summary><pre>{html.escape(text)}</pre></details>
<details><summary>Computed grades</summary><pre>{html.escape(json.dumps(grades,indent=2))}</pre></details>
<details><summary>Readiness and full read-back checks</summary><pre>{html.escape(json.dumps({'readiness':results['readiness'],'verification':results['verification']},indent=2))}</pre></details>
</main></html>"""
    (root / "report.html").write_text(document)
    return text
