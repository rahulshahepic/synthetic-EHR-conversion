# Briar discovery transcript

Synthetic deterministic analysts; fixture and interview authored by the same assistant. No claim of a blinded evaluation.

**E000096 · interviewer → systems**

Is the old dictionary current on identity, DOB, timestamps, money and appointment R?

Reason: Establish the systems owner's position.

**E000097 · simulated systems**

It is still the approved guide. CHART is enterprise-wide, the DOB window is 1950, all bill amounts are cents, and R is rescheduled. Registration should be able to confirm.

**E000098 · interviewer → registration**

Is CHART enterprise-wide, and may identical demographics be merged?

Reason: Repeated chart numbers and separate installations challenge enterprise identity.

**E000099 · simulated registration**

No. A and B allocate the same chart numbers independently. Key by SITE plus CHART. Same name and DOB can be twins or duplicate charts. We routinely merge the obvious duplicates; I would just merge those two.

**E000100 · interviewer → registration**

How are DOB and no-known-allergy flags actually used?

Reason: DOB shapes and allergy conflicts require their operational owner.

**E000101 · simulated registration**

Current registrations are YYYYMMDD. Older imported rows sometimes have YYMMDD; my window is 1930-2029. Blank is unknown. NKA is sticky after an allergy is added, so preserve the positive allergy and clear the NKA flag on conflicts.

**E000102 · interviewer → lab**

Are all glucose units now mmol/L at Outreach?

Reason: A scheduled migration does not establish that every device changed.

**E000103 · simulated lab**

Yes, everything at B switched on January 1. A is mg/dL. You can ignore the per-row unit now.

**E000104 · interviewer → pharmacy**

What does MED H mean, and can MISC be skipped?

Reason: Version skew and missing drug mappings can lose active therapy.

**E000105 · simulated pharmacy**

H now means temporarily on hold; it is not historical. I know the old guide says otherwise. MISC is a real compound or a med with no formulary match; don't silently skip it or invent an RxNorm code. The text and sig need to remain in the source archive until someone identifies it.

**E000106 · interviewer → billing**

Are all BILL amounts cents and can credits be imported as charges?

Reason: Decimal and negative amounts contradict a global cents rule.

**E000107 · simulated billing**

No. A is cents; B switched to decimal dollars for service dates 20260101 and later. Earlier B stays cents, even if extracted today. Negative rows are credits. Do not flip their sign or turn them into debit charges; Nimbus needs a credit workflow we don't have here.

**E000112 · interviewer → systems**

The support note and data conflict with that guide; which delivery contract applies?

Reason: The 3.7 layout conflicts with the approved 2.3 guide.

**E000113 · simulated systems**

LAYOUTS 3.7 describes the file spans. The 2.3 guide has not been rewritten. Both sites use Chicago local time. 2400 is next-day midnight, but 2461 is invalid. DST repeated and missing hours cannot be disambiguated from these files.

**E000114 · interviewer → systems**

Registration says current DOB is YYYYMMDD and CHART is site-scoped; do you have contrary delivery evidence?

Reason: Ask for evidence rather than settle by seniority.

**E000115 · simulated systems**

No. I was describing the old installation. Use what the 3.7 delivery actually shows; I don't have an MPI extract.

**E000116 · interviewer → registration**

Can you establish the century for six-digit DOBs or prove the matching charts are one person?

Reason: Name and date shape prove neither identity nor century.

**E000117 · simulated registration**

Not from this delivery. I would need the old paper register and chart audit. Leave those birth dates and possible merges for review.

**E000118 · interviewer → lab**

The B data still contains mg/dL; what supports ignoring it?

Reason: Measured B-site rows contradict the initial blanket unit claim.

**E000119 · simulated lab**

The chemistry analyzer switched, but the point-of-care devices may not have. I cannot tell you which produced those rows. Use the transmitted unit, and do not infer a conversion from the value alone.

**E000120 · interviewer → lab**

What do nonnumeric results, 999999, suffix flags, revisions and journal deletes mean?

Reason: Distinguish valid text, missing values, corrections and withdrawals.

**E000121 · simulated lab**

NEG is a valid culture result, not a bench error. 999999 is the old no-result sentinel, not a numeric result. H/L follow the result, including comparator results. Larger REV is current. A delete for an accession withdraws every test on that accession, not just potassium. Don't resurrect the old revision.

**E000122 · interviewer → lab**

Can missing lab units always be filled from the dictionary?

Reason: A mixed-device population invalidates a universal glucose default.

**E000123 · simulated lab**

For potassium here yes, mmol/L. For glucose no: an empty unit after the device migration needs a chart check. The absent-result sentinel should stay absent, not become a glucose concentration.

**E000124 · interviewer → pharmacy**

Does the same H meaning apply to old archived medication exports?

Reason: Limit the rule to the supported version.

**E000125 · simulated pharmacy**

I only own the current 3.7 delivery. I cannot attest to H before the upgrade; do not apply this answer to an old delivery without its own review.

**E000126 · interviewer → systems**

What is APPT R in the current delivery?

Reason: Physical shapes cannot establish a status meaning.

**E000127 · simulated systems**

I think rescheduled. Scheduling told me it may be a legacy arrived state after a migration. I cannot prove either from an appointment row. Scheduling is not available today.

**E000128 · interviewer → systems**

Are full-width note segments necessarily truncated, and how do journal deletions apply?

Reason: Full width is not proof of lost text; establish assembly and delete scope.

**E000129 · simulated systems**

No, a full segment can continue in the next SEQ. The export has no original length or truncation marker. Join SEQ numerically within SITE and ID. An accession delete in JRN withdraws the entire accession. A document can still have been truncated before export; we can't recover what never arrived.

**E000131 · resolution: identity / keying_story**

{"key_fields": ["REG.TXT.SITE+REG.TXT.CHART"], "master_index": false}

Systems withdrew old enterprise-ID assertion; registration and site collisions agree. No patient merges authorized.

**E000133 · resolution: field:REG.TXT.DOB / convention**

{"format": "YYYYMMDD", "other": "runtime_question"}

Eight-digit rows parse; six-digit century and missing dates cannot be established.

**E000135 · resolution: field:LAB.TXT.UNIT / convention**

"row_unit_overrides_dictionary"

Initial blanket site conversion was contradicted by B-site unit labels and withdrawn.

**E000137 · resolution: field:MED.TXT.STATUS / convention**

{"A": "active", "H": "on-hold", "S": "stopped"}

Pharmacy confirms current 3.7 delivery only; archived H remains out of scope.

**E000139 · resolution: field:BILL.TXT.AMOUNT / convention**

{"dollars_from_service_date": "20260101", "negative": "runtime_question", "otherwise": "cents", "site": "B"}

Follow-up with domain owner; delivery evidence checked

**E000141 · resolution: field:LAB.TXT.RESULT / convention**

{"NEG": "negative", "comparator": "preserve", "missing_sentinel": "999999", "numeric_flags": true, "other_text": "preserve"}

Follow-up with domain owner; delivery evidence checked
