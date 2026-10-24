"""Tests for the T-102 free-text medication sig parser (all sigs synthetic)."""
import pytest

from bridge.normalize.sig import SigResult, parse_sig

_BASE = dict(
    dose_value=None, dose_unit=None, route=None,
    frequency_count=None, frequency_period=None, frequency_period_unit=None,
    as_needed=False, as_needed_reason=None, duration_days=None,
    confidence=1.0, unparsed="",
)

_D = dict(frequency_count=1, frequency_period=1.0, frequency_period_unit="d")


@pytest.mark.parametrize(("text", "expected"), [
    # --- dose + route + Latin frequency -------------------------------------
    ("1 tab po daily", dict(dose_value=1.0, dose_unit="{tab}", route="oral", **_D)),
    ("1 TAB PO QD", dict(dose_value=1.0, dose_unit="{tab}", route="oral", **_D)),
    ("1 tab po bid", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                          frequency_count=2, frequency_period=1.0,
                          frequency_period_unit="d")),
    ("1 TAB PO BID WITH MEALS", dict(dose_value=1.0, dose_unit="{tab}",
                                     route="oral", frequency_count=2,
                                     frequency_period=1.0,
                                     frequency_period_unit="d")),
    ("500mg po bid", dict(dose_value=500.0, dose_unit="mg", route="oral",
                          frequency_count=2, frequency_period=1.0,
                          frequency_period_unit="d")),
    ("5 mg by mouth twice daily", dict(dose_value=5.0, dose_unit="mg",
                                       route="oral", frequency_count=2,
                                       frequency_period=1.0,
                                       frequency_period_unit="d")),
    ("1 tab po tid", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                          frequency_count=3, frequency_period=1.0,
                          frequency_period_unit="d")),
    ("1 tab po qid", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                          frequency_count=4, frequency_period=1.0,
                          frequency_period_unit="d")),
    ("1 tab po qhs", dict(dose_value=1.0, dose_unit="{tab}", route="oral", **_D)),
    ("1 tab by mouth at bedtime", dict(dose_value=1.0, dose_unit="{tab}",
                                       route="oral", **_D)),
    ("1 tab po qam", dict(dose_value=1.0, dose_unit="{tab}", route="oral", **_D)),
    ("1 cap po daily ac", dict(dose_value=1.0, dose_unit="{cap}", route="oral",
                               **_D)),
    ("1 tab po daily before breakfast", dict(dose_value=1.0, dose_unit="{tab}",
                                             route="oral", **_D)),
    ("take one tablet by mouth once daily",
     dict(dose_value=1.0, dose_unit="{tab}", route="oral", **_D)),
    ("take 1 tablet by mouth every morning",
     dict(dose_value=1.0, dose_unit="{tab}", route="oral", **_D)),
    ("1 tab po three times a day", dict(dose_value=1.0, dose_unit="{tab}",
                                        route="oral", frequency_count=3,
                                        frequency_period=1.0,
                                        frequency_period_unit="d")),
    ("3 tabs po once daily", dict(dose_value=3.0, dose_unit="{tab}",
                                   route="oral", **_D)),
    ("2 tabs po bid", dict(dose_value=2.0, dose_unit="{tab}", route="oral",
                           frequency_count=2, frequency_period=1.0,
                           frequency_period_unit="d")),
    # --- doses: strengths, fractions, units ----------------------------------
    ("2.5 mg po daily", dict(dose_value=2.5, dose_unit="mg", route="oral", **_D)),
    ("0.5 mg po daily", dict(dose_value=0.5, dose_unit="mg", route="oral", **_D)),
    ("50mcg po daily", dict(dose_value=50.0, dose_unit="ug", route="oral", **_D)),
    ("1/2 tab po qhs", dict(dose_value=0.5, dose_unit="{tab}", route="oral", **_D)),
    ("½ tab po daily", dict(dose_value=0.5, dose_unit="{tab}", route="oral", **_D)),
    ("1 1/2 tabs po daily", dict(dose_value=1.5, dose_unit="{tab}", route="oral",
                                 **_D)),
    ("10 units subq qhs", dict(dose_value=10.0, dose_unit="[iU]", route="subcut",
                               **_D)),
    ("22 UNITS SQ AT BEDTIME", dict(dose_value=22.0, dose_unit="[iU]",
                                    route="subcut", **_D)),
    ("10 units sc daily", dict(dose_value=10.0, dose_unit="[iU]", route="subcut",
                               **_D)),
    ("5 ml po bid", dict(dose_value=5.0, dose_unit="mL", route="oral",
                         frequency_count=2, frequency_period=1.0,
                         frequency_period_unit="d")),
    ("1 tsp po bid", dict(dose_value=5.0, dose_unit="mL", route="oral",
                          frequency_count=2, frequency_period=1.0,
                          frequency_period_unit="d")),
    ("15 mg im daily", dict(dose_value=15.0, dose_unit="mg", route="im", **_D)),
    ("10 mg iv q8h", dict(dose_value=10.0, dose_unit="mg", route="iv",
                          frequency_count=1, frequency_period=8.0,
                          frequency_period_unit="h")),
    ("10 mg pr daily", dict(dose_value=10.0, dose_unit="mg", route="rectal",
                            **_D)),
    # --- intervals and PRN -----------------------------------------------------
    ("1 tab po q6h prn pain", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                                   frequency_count=1, frequency_period=6.0,
                                   frequency_period_unit="h", as_needed=True,
                                   as_needed_reason="pain")),
    ("1 tab po q12h", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                           frequency_count=1, frequency_period=12.0,
                           frequency_period_unit="h")),
    ("1 tab po every 6 hours", dict(dose_value=1.0, dose_unit="{tab}",
                                    route="oral", frequency_count=1,
                                    frequency_period=6.0,
                                    frequency_period_unit="h")),
    ("1 tab po q8h prn pain with food",
     dict(dose_value=1.0, dose_unit="{tab}", route="oral", frequency_count=1,
          frequency_period=8.0, frequency_period_unit="h", as_needed=True,
          as_needed_reason="pain")),
    ("600mg po tid prn", dict(dose_value=600.0, dose_unit="mg", route="oral",
                              frequency_count=3, frequency_period=1.0,
                              frequency_period_unit="d", as_needed=True)),
    ("1 tab po qhs prn", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                              as_needed=True, **_D)),
    ("2 PUFFS Q4H PRN WHEEZING", dict(dose_value=2.0, dose_unit="{puff}",
                                      frequency_count=1, frequency_period=4.0,
                                      frequency_period_unit="h", as_needed=True,
                                      as_needed_reason="wheezing")),
    ("swish and spit 10ml qid prn",
     dict(dose_value=10.0, dose_unit="mL", frequency_count=4,
          frequency_period=1.0, frequency_period_unit="d", as_needed=True)),
    # --- ranges: lower-bound dose / upper-bound interval, noted, low conf -----
    ("1-2 tabs po q6h prn pain",
     dict(dose_value=1.0, dose_unit="{tab}", route="oral", frequency_count=1,
          frequency_period=6.0, frequency_period_unit="h", as_needed=True,
          as_needed_reason="pain", confidence=0.4, unparsed="1-2")),
    ("1 tab po q4-6h prn",
     dict(dose_value=1.0, dose_unit="{tab}", route="oral", frequency_count=1,
          frequency_period=6.0, frequency_period_unit="h", as_needed=True,
          confidence=0.4, unparsed="q4-6h")),
    ("2 puffs inh q4-6h prn sob",
     dict(dose_value=2.0, dose_unit="{puff}", route="inhaled",
          frequency_count=1, frequency_period=6.0, frequency_period_unit="h",
          as_needed=True, as_needed_reason="sob", confidence=0.4,
          unparsed="q4-6h")),
    # --- durations --------------------------------------------------------------
    ("1 cap po tid x10d", dict(dose_value=1.0, dose_unit="{cap}", route="oral",
                               frequency_count=3, frequency_period=1.0,
                               frequency_period_unit="d", duration_days=10)),
    ("1 CAP PO TID X 10 DAYS", dict(dose_value=1.0, dose_unit="{cap}",
                                    route="oral", frequency_count=3,
                                    frequency_period=1.0,
                                    frequency_period_unit="d", duration_days=10)),
    ("4 tabs po daily x5d", dict(dose_value=4.0, dose_unit="{tab}", route="oral",
                                 duration_days=5, **_D)),
    ("1 tab po bid x 2 weeks", dict(dose_value=1.0, dose_unit="{tab}",
                                    route="oral", frequency_count=2,
                                    frequency_period=1.0,
                                    frequency_period_unit="d", duration_days=14)),
    ("1 cap po qd for 7 days", dict(dose_value=1.0, dose_unit="{cap}",
                                    route="oral", duration_days=7, **_D)),
    ("1 tab po daily x30d", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                                 duration_days=30, **_D)),
    # --- other frequencies -------------------------------------------------------
    ("1 tab po every other day", dict(dose_value=1.0, dose_unit="{tab}",
                                      route="oral", frequency_count=1,
                                      frequency_period=2.0,
                                      frequency_period_unit="d")),
    ("1 tab po qod", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                          frequency_count=1, frequency_period=2.0,
                          frequency_period_unit="d")),
    ("1 tab po weekly", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                             frequency_count=1, frequency_period=1.0,
                             frequency_period_unit="wk")),
    ("1 tab po once a week", dict(dose_value=1.0, dose_unit="{tab}",
                                  route="oral", frequency_count=1,
                                  frequency_period=1.0,
                                  frequency_period_unit="wk")),
    # --- routes via phrases -------------------------------------------------------
    ("1 drop in each eye bid", dict(dose_value=1.0, dose_unit="{drop}",
                                    route="ophthalmic", frequency_count=2,
                                    frequency_period=1.0,
                                    frequency_period_unit="d")),
    ("1 drop in each ear tid", dict(dose_value=1.0, dose_unit="{drop}",
                                    route="otic", frequency_count=3,
                                    frequency_period=1.0,
                                    frequency_period_unit="d")),
    ("2 drops in each nostril daily", dict(dose_value=2.0, dose_unit="{drop}",
                                           route="nasal", **_D)),
    ("1 tab sl daily", dict(dose_value=1.0, dose_unit="{tab}",
                            route="sublingual", **_D)),
    ("1 tab under the tongue daily", dict(dose_value=1.0, dose_unit="{tab}",
                                          route="sublingual", **_D)),
    # --- partial structure: one of dose/frequency missing --------------------------
    ("1 tab po pc", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                         confidence=0.8)),
    ("po bid", dict(route="oral", frequency_count=2, frequency_period=1.0,
                    frequency_period_unit="d", confidence=0.8)),
    ("1 tab po", dict(dose_value=1.0, dose_unit="{tab}", route="oral",
                      confidence=0.8)),
    # --- as directed / unparseable ---------------------------------------------------
    ("ud per INR clinic", dict(confidence=0.3, unparsed="inr clinic")),
    ("take as directed", dict(confidence=0.3)),
    ("taper as directed", dict(confidence=0.3, unparsed="taper")),
    ("see note", dict(confidence=0.1, unparsed="see note")),
    ("", dict(confidence=0.0)),
    ("apply cream to skin daily", dict(frequency_count=1, frequency_period=1.0,
                                       frequency_period_unit="d", confidence=0.2,
                                       unparsed="cream skin")),
    ("1 tab po bid for pain", dict(dose_value=1.0, dose_unit="{tab}",
                                   route="oral", frequency_count=2,
                                   frequency_period=1.0, frequency_period_unit="d",
                                   confidence=0.4, unparsed="pain")),
])
def test_parse_sig(text, expected):
    want = SigResult(**{**_BASE, **expected})
    got = parse_sig(text)
    assert got == want
    if want.unparsed:
        # spec rule: a clinically material unparsed token caps confidence < 0.5
        assert got.confidence < 0.5


def test_non_str_input_raises():
    with pytest.raises(TypeError):
        parse_sig(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        parse_sig(42)  # type: ignore[arg-type]


@pytest.mark.parametrize("text", [
    "1 tab po bid xyzq",          # garbage token
    "1-2 tabs po daily",          # dose range
    "1 tab po q4-6h",             # interval range
    "taper as directed",          # unmodeled instruction
    "see note",                   # no structure at all
    "alternate 1 tab and 2 tabs daily",  # alternating doses unhandled
])
def test_material_leftovers_cap_confidence(text):
    result = parse_sig(text)
    assert result.unparsed
    assert result.confidence < 0.5


def test_timing_annotations_do_not_count_as_unparsed():
    result = parse_sig("1 tab po bid with meals")
    assert result.unparsed == ""
    assert result.confidence == 1.0


def test_result_is_immutable():
    result = parse_sig("1 tab po daily")
    with pytest.raises(Exception):
        result.dose_value = 99.0  # type: ignore[misc]


@pytest.mark.parametrize(("sig", "expected"), [
    ("inject 10 units under the skin at bedtime", {"route": "subcut", "dose_value": 10.0}),
    ("take 1 tablet by mouth two times daily", {"frequency_count": 2}),
    ("take 1 capsule by mouth three times daily for 10 days", {"frequency_count": 3, "duration_days": 10}),
    ("swish and spit 10 mL four times daily as needed", {"frequency_count": 4, "as_needed": True}),
    ("inhale 2 puffs every 4 to 6 hours as needed for wheezing", {"frequency_period": 6.0, "as_needed_reason": "wheezing", "confidence": 0.4}),
])
def test_lakeside_sentence_style(sig, expected):
    parsed = parse_sig(sig)
    for field, value in expected.items():
        assert getattr(parsed, field) == value


# Every generated source sig must remain parseable, not just handpicked examples.
from testbed.halcyon.profiles.lakeside import LAKESIDE_SIGS
from testbed.halcyon.vocab import FORMULARY


@pytest.mark.parametrize(("code", "sig"), [
    (code, sig) for code, variants in LAKESIDE_SIGS.items() for sig in variants
])
def test_every_lakeside_formulary_sig(code, sig):
    assert code in FORMULARY
    parsed = parse_sig(sig)
    if sig == "see note":
        assert parsed.confidence < 0.5
        assert parsed.unparsed
    elif "as directed" in sig:
        assert parsed.confidence <= 0.3
    else:
        assert parsed.dose_value is not None, (code, sig, parsed)
        assert parsed.frequency_count is not None, (code, sig, parsed)
        assert parsed.frequency_period is not None, (code, sig, parsed)
        assert parsed.confidence >= 0.4, (code, sig, parsed)
    if "under the skin" in sig or "subcutaneously" in sig:
        assert parsed.route == "subcut"
    if sig.startswith("inhale"):
        assert parsed.route == "inhaled"
    if " to " in sig:
        assert parsed.confidence < 0.5


@pytest.mark.parametrize(("code", "sig"), [
    (code, sig) for code, item in FORMULARY.items() for sig in item[3]
])
def test_every_default_formulary_sig(code, sig):
    parsed = parse_sig(sig)
    assert 0 <= parsed.confidence <= 1, (code, sig)
    if "as directed" not in sig and "ud " not in sig and "see note" not in sig:
        assert parsed.dose_value is not None or parsed.frequency_count is not None, (code, sig)


# Explicit expectations for every sig variant in both source formularies.
# Columns: dose, unit, route, count, period, period_unit, PRN, duration.
N = None
L = {
 "HFORM0001": [(1,"{tab}","oral",1,1,"d",False,N)]*2,
 "HFORM0002": [(1,"{tab}","oral",2,1,"d",False,N)]*2,
 "HFORM0003": [(1,"{tab}","oral",1,1,"d",False,N)]*2,
 "HFORM0004": [(1,"{tab}","oral",1,1,"d",False,N),(.5,"{tab}","oral",1,1,"d",False,N),(N,N,N,N,N,N,False,N)],
 "HFORM0005": [(10,"[iU]","subcut",1,1,"d",False,N),(22,"[iU]","subcut",1,1,"d",False,N)],
 "HFORM0006": [(1,"{cap}","oral",3,1,"d",False,10),(1,"{cap}","oral",1,8,"h",False,10)],
 "HFORM0007": [(2,"{puff}","inhaled",1,6,"h",True,N),(2,"{puff}","inhaled",1,4,"h",True,N)],
 "HFORM0008": [(1,"{tab}","oral",1,1,"d",False,N)]*2,
 "HFORM0009": [(1,"{cap}","oral",1,1,"d",False,N)]*2,
 "HFORM0010": [(1,"{tab}","oral",1,6,"h",True,N)]*2,
 "HFORM0011": [(1,"{tab}","oral",2,1,"d",False,N)]*2,
 "HFORM0012": [(1,"{tab}","oral",1,1,"d",False,N)]*2,
 "HFORM0013": [(1,"{tab}","oral",3,1,"d",True,N),(1,"{tab}","oral",1,8,"h",True,N)],
 "HFORM0014": [(N,N,N,N,N,N,False,N),(4,"{tab}","oral",1,1,"d",False,5)],
 "HFORM0015": [(10,"mL",N,4,1,"d",True,N),(10,"mL",N,1,6,"h",True,N)],
 "HFORM0099": [(N,N,N,N,N,N,False,N)],
}
R = {
 "HFORM0001": [(1,"{tab}","oral",1,1,"d",False,N)]*3,
 "HFORM0002": [(1,"{tab}","oral",2,1,"d",False,N)]*2+[(500,"mg","oral",2,1,"d",False,N)],
 "HFORM0003": [(1,"{tab}","oral",1,1,"d",False,N)]*2,
 "HFORM0004": [(1,"{tab}","oral",1,1,"d",False,N),(.5,"{tab}","oral",1,1,"d",False,N),(N,N,N,N,N,N,False,N)],
 "HFORM0005": [(10,"[iU]","subcut",1,1,"d",False,N),(22,"[iU]","subcut",1,1,"d",False,N)],
 "HFORM0006": [(1,"{cap}","oral",3,1,"d",False,10)]*2,
 "HFORM0007": [(2,"{puff}","inhaled",1,6,"h",True,N),(2,"{puff}",N,1,4,"h",True,N)],
 "HFORM0008": [(1,"{tab}","oral",1,1,"d",False,N)]*2,
 "HFORM0009": [(1,"{cap}","oral",1,1,"d",False,N)]*2,
 "HFORM0010": [(1,"{tab}","oral",1,6,"h",True,N)]*2,
 "HFORM0011": [(1,"{tab}","oral",2,1,"d",False,N),(5,"mg","oral",2,1,"d",False,N)],
 "HFORM0012": [(1,"{tab}","oral",1,1,"d",False,N)]*2,
 "HFORM0013": [(1,"{tab}","oral",1,8,"h",True,N),(600,"mg","oral",3,1,"d",True,N)],
 "HFORM0014": [(N,N,N,N,N,N,False,N),(4,"{tab}","oral",1,1,"d",False,5)],
 "HFORM0015": [(10,"mL",N,4,1,"d",True,N)],
 "HFORM0099": [(N,N,N,N,N,N,False,N)],
}

@pytest.mark.parametrize(("source", "code", "index", "sig", "expected"), [
    (source, code, i, sig, cases[code][i])
    for source, formulary, cases in (
        ("lakeside", LAKESIDE_SIGS, L),
        ("riverbend", {code: row[3] for code, row in FORMULARY.items()}, R),
    )
    for code, sigs in formulary.items()
    for i, sig in enumerate(sigs)
])
def test_all_formulary_sig_expected_fields(source, code, index, sig, expected):
    parsed = parse_sig(sig)
    actual = (parsed.dose_value, parsed.dose_unit, parsed.route,
              parsed.frequency_count, parsed.frequency_period,
              parsed.frequency_period_unit, parsed.as_needed, parsed.duration_days)
    assert actual == expected, (source, code, index, sig, actual, expected)
    if " to " in sig or "1-2" in sig or "q4-6h" in sig:
        assert parsed.confidence < 0.5
    if sig == "inhale 2 puffs every 4 to 6 hours as needed for shortness of breath":
        assert parsed.as_needed_reason == "shortness of breath"
