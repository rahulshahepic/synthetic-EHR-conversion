"""Private deterministic analyst backend. Interviewers use ask(), never inspect this file.

Fixture authors provide this knowledge. There is no LLM/human independence claim.
"""
from pathlib import Path

from bridge.interview.analysts import AnalystService, EstateReader, StubAnalyst


def service(estate: Path) -> AnalystService:
    profiles = {
        "registration": ("Mira Vale", {
            "Is CHART enterprise-wide, and may identical demographics be merged?": "No. A and B allocate the same chart numbers independently. Key by SITE plus CHART. Same name and DOB can be twins or duplicate charts. We routinely merge the obvious duplicates; I would just merge those two.",
            "How are DOB and no-known-allergy flags actually used?": "Current registrations are YYYYMMDD. Older imported rows sometimes have YYMMDD; my window is 1930-2029. Blank is unknown. NKA is sticky after an allergy is added, so preserve the positive allergy and clear the NKA flag on conflicts.",
            "Can you establish the century for six-digit DOBs or prove the matching charts are one person?": "Not from this delivery. I would need the old paper register and chart audit. Leave those birth dates and possible merges for review.",
        }),
        "lab": ("Tomas Reed", {
            "Are all glucose units now mmol/L at Outreach?": "Yes, everything at B switched on January 1. A is mg/dL. You can ignore the per-row unit now.",
            "The B data still contains mg/dL; what supports ignoring it?": "The chemistry analyzer switched, but the point-of-care devices may not have. I cannot tell you which produced those rows. Use the transmitted unit, and do not infer a conversion from the value alone.",
            "What do nonnumeric results, 999999, suffix flags, revisions and journal deletes mean?": "NEG is a valid culture result, not a bench error. 999999 is the old no-result sentinel, not a numeric result. H/L follow the result, including comparator results. Larger REV is current. A delete for an accession withdraws every test on that accession, not just potassium. Don't resurrect the old revision.",
            "Can missing lab units always be filled from the dictionary?": "For potassium here yes, mmol/L. For glucose no: an empty unit after the device migration needs a chart check. The absent-result sentinel should stay absent, not become a glucose concentration.",
        }),
        "pharmacy": ("Anya Moss", {
            "What does MED H mean, and can MISC be skipped?": "H now means temporarily on hold; it is not historical. I know the old guide says otherwise. MISC is a real compound or a med with no formulary match; don't silently skip it or invent an RxNorm code. The text and sig need to remain in the source archive until someone identifies it.",
            "Does the same H meaning apply to old archived medication exports?": "I only own the current 3.7 delivery. I cannot attest to H before the upgrade; do not apply this answer to an old delivery without its own review.",
        }),
        "systems": ("Glen Pike", {
            "Is the old dictionary current on identity, DOB, timestamps, money and appointment R?": "It is still the approved guide. CHART is enterprise-wide, the DOB window is 1950, all bill amounts are cents, and R is rescheduled. Registration should be able to confirm.",
            "The support note and data conflict with that guide; which delivery contract applies?": "LAYOUTS 3.7 describes the file spans. The 2.3 guide has not been rewritten. Both sites use Chicago local time. 2400 is next-day midnight, but 2461 is invalid. DST repeated and missing hours cannot be disambiguated from these files.",
            "Registration says current DOB is YYYYMMDD and CHART is site-scoped; do you have contrary delivery evidence?": "No. I was describing the old installation. Use what the 3.7 delivery actually shows; I don't have an MPI extract.",
            "What is APPT R in the current delivery?": "I think rescheduled. Scheduling told me it may be a legacy arrived state after a migration. I cannot prove either from an appointment row. Scheduling is not available today.",
            "Are full-width note segments necessarily truncated, and how do journal deletions apply?": "No, a full segment can continue in the next SEQ. The export has no original length or truncation marker. Join SEQ numerically within SITE and ID. An accession delete in JRN withdraws the entire accession. A document can still have been truncated before export; we can't recover what never arrived.",
        }),
        "billing": ("Inez Fern", {
            "Are all BILL amounts cents and can credits be imported as charges?": "No. A is cents; B switched to decimal dollars for service dates 20260101 and later. Earlier B stays cents, even if extracted today. Negative rows are credits. Do not flip their sign or turn them into debit charges; Nimbus needs a credit workflow we don't have here.",
        }),
    }
    return AnalystService({aid: StubAnalyst(aid, name, answers, unknown_response="I don't know; please ask the owning department.") for aid, (name, answers) in profiles.items()}, EstateReader([estate]))
