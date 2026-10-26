"""The Meridian interview: the recorded ledger replays to the committed spec, the recorded
profiler events are what the profiler really observes, and the generated canonical binding
(delimited reader, field expressions, crosswalk overlay) behaves as documented."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.interview import canonical, claims as claims_mod, ledger as ledger_mod, specgen
from bridge.interview.analysts import AnalystService, EstateReader, StubAnalyst, replay_questions
from bridge.interview.profiler import profile_export
from bridge.profiles import load_profile
from bridge.terminology import TERMS, OverlayTerminology, terms_for
from tools.interview import _inventory, stub_analysts

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "src/bridge/interview/ledgers/meridian.jsonl"
SPEC_DIR = ROOT / "src/bridge/interview/specs/meridian"


@pytest.fixture(scope="module")
def events():
    return ledger_mod.read_events(LEDGER)


@pytest.fixture(scope="module")
def pkg(events):
    return specgen.generate_spec(events, claims_mod.ClaimStore.from_ledger(events), "meridian",
                                 inventory=_inventory(events))


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    from testbed.meridian.generator import generate  # the export the interview was recorded against
    out = tmp_path_factory.mktemp("meridian")
    generate(out, seed=42, patients=300)
    return out


def test_ledger_replays_to_the_committed_spec(events, pkg):
    assert pkg.spec_json() == (SPEC_DIR / "spec.json").read_text()
    assert pkg.profile_code == (SPEC_DIR / "profile.py").read_text()
    assert json.loads((SPEC_DIR / "reader_binding.json").read_text()) == pkg.reader_binding
    assert json.loads((SPEC_DIR / "stub_analysts.json").read_text()) == stub_analysts(events)


def test_stub_replay_byte_for_byte(events, tmp_path):
    stub = json.loads((SPEC_DIR / "stub_analysts.json").read_text())
    analysts = {aid: StubAnalyst(id=aid, name=c["name"], answers=c["answers"], blind_spots=c["blind_spots"],
                                 outside_response=c["outside_response"]) for aid, c in stub.items()}
    assert set(analysts) == {"registration", "lab", "pharmacy", "interface"}
    assert replay_questions(events, AnalystService(analysts, EstateReader([tmp_path]))) == []


def test_recorded_profiler_events_match_a_fresh_profile(events, export):
    """The ledger's inventory and observations were written by the profiler from this export,
    not by hand: re-profiling it reproduces them exactly."""
    inv = next(e for e in events if e.type == "inventory").payload
    report = profile_export(export, delimited=inv["profiler"]["delimited"],
                            code_value_limit=inv["profiler"]["code_value_limit"])
    assert specgen.recorded_inventory(events) == {n: sorted(f["fields"]) for n, f in report["files"].items()}
    recorded = claims_mod.observation_payloads(events)
    assert {o["id"]: o["stats"] for o in report["observations"]} == {k: v["stats"] for k, v in recorded.items()}


def test_estate_firewall_refuses_answer_key_and_profiles(export):
    reader = EstateReader([export])
    assert "MCS/2" in reader.read("MCS2_EXTRACT_GUIDE.TXT")
    for doc in ("answer_key/truth.json", "answer_key/estate_discrepancies.json", "../analysts/lab.md"):
        with pytest.raises((PermissionError, FileNotFoundError)):
            reader.read(doc)


def test_spec_carries_the_interview_findings(pkg):
    rules = {(r["subject"], r["predicate"]): r for r in pkg.spec["rules"]}
    tz = rules[("profile", "facility_tz")]
    assert tz["value"] == {"HVMC": "America/Denver", "SRC": "America/Phoenix"}
    assert tz["data_confirmed"] and tz["provenance"]["kind"] == "analyst"
    assert rules[("identity", "keying_story")]["value"]["true_duplicates"] is True
    assert "X=cancelled" in rules[("field:LABRES.DAT.RESULT_STATUS", "convention")]["value"]
    assert "Parse both" in rules[("field:LABRES.DAT.COLLECTED_TS", "convention")]["value"]
    assert "on hold" in rules[("field:RXORDER.DAT.RX_STATUS", "convention")]["value"]  # the guide over the pharmacist
    assert rules[("codeset:formulary", "crosswalk")]["value"]["MD0108"] == "966222"    # drug-file error corrected
    assert rules[("codeset:formulary", "handling_unmapped")]["value"].startswith("route every order")
    unknowns = {(u["subject"], u["predicate"]) for u in pkg.spec["known_unknowns"]}
    assert ("field:APPT.DAT.APPT_STATUS", "convention") in unknowns  # nobody could explain BMP
    assert next(r for r in pkg.spec["rules"] if r["id"] == "SAFETY-IDENTITY-MERGE")["value"] == "route_to_reconciliation"


def test_generated_profile_loads_and_names_its_reader():
    profile = load_profile("meridian")
    assert profile.READER == "delimited" and profile.MERGE_POLICY == "route_to_reconciliation"
    assert profile.FACILITY_TZ["SRC"] == "America/Phoenix"
    assert load_profile(None).__name__ == "bridge.profiles.halcyon"
    with pytest.raises(ValueError):
        load_profile("../halcyon")


def test_reader_binding_declares_format_and_canonical_types(pkg):
    b = pkg.reader_binding
    assert b["format"] == {"delimiter": "|", "encoding": "latin-1", "suffix": ".DAT"}
    assert [m["kind"] for m in b["canonical"]["Observation"]] == ["lab", "vital"]
    assert {"Patient", "Encounter", "Condition", "MedicationRequest", "Appointment"} <= set(b["canonical"])


# ----------------------------------------------------------------------------- canonical binding units
class _Exp:
    def __init__(self, files):
        self.files = files

    def rows(self, stem):
        return self.files[stem]


def test_cases_lookup_chain_and_annotations():
    ev = canonical.Evaluator(_Exp({"VISIT": [{"VISIT_NO": "1", "CLINIC_CD": "SRFM"}],
                                   "CLINIC": [{"CLINIC_CD": "SRFM", "CAMPUS_CD": "SRC"}]}))
    campus = {"field": "VISIT_NO", "lookup": [{"file": "VISIT", "key": "VISIT_NO", "value": "CLINIC_CD"},
                                              {"file": "CLINIC", "key": "CLINIC_CD", "value": "CAMPUS_CD"}]}
    expr = {"cases": [{"if": {"all": [{"value": "U", "blank": True}, {"value": campus, "in": ["SRC"]},
                                      {"value": {"field": "T", "date": "%m/%d/%Y"}, "before": "20160301"}]},
                       "then": {"concat": ["V", {"const": " "}, {"const": "lb"}]},
                       "annotate": {"field": "unit", "klass": "inferred", "note": "migrated"}}],
            "else": {"format": "{V} {U}"}}
    mapping = {"fields": {"VALUE": expr}}
    old = ev.record(mapping, {"V": "150", "U": "", "VISIT_NO": "1", "T": "02/01/2015"})
    assert old == {"VALUE": "150 lb", "_canonical_notes": [{"field": "unit", "klass": "inferred", "note": "migrated"}]}
    assert ev.record(mapping, {"V": "70", "U": "kg", "VISIT_NO": "1", "T": "02/01/2020"}) == {"VALUE": "70 kg"}
    multi = {"field": "T", "datetime": ["%d-%b-%y %H:%M", "%Y-%m-%d %H:%M"]}
    assert ev.value(multi, {"T": "2024-03-05 08:15"}) == ev.value(multi, {"T": "05-MAR-24 08:15"}) == "202403050815"
    assert ev.value({"field": "T", "upper": True}, {"T": "th"}) == "TH"


def test_exclude_unless_keeps_and_annotates():
    ev = canonical.Evaluator(_Exp({}))
    m = {"exclude": {"S": ["VOID"]}, "exclude_unless": {"value": "T", "in": ["ER"]}}
    assert canonical._excluded(m, {"S": "VOID", "T": "ER"}, ev) is None
    assert canonical._excluded(m, {"S": "VOID", "T": "OP"}, ev)


@pytest.mark.parametrize("expr,row,want", [
    ("A", {"A": "x"}, "x"),
    ({"const": "SYS"}, {}, "SYS"),
    ({"format": "{L},{F} {M}"}, {"L": "KIM", "F": "SOFIA", "M": ""}, "KIM,SOFIA"),
    ({"field": "D", "null_values": ["01/01/1900"], "date": "%m/%d/%Y"}, {"D": "01/01/1900"}, ""),
    ({"field": "D", "date": "%m/%d/%Y"}, {"D": "03/12/1984"}, "19840312"),
    ({"field": "D", "date": "%m/%d/%Y"}, {"D": "13/45/1984"}, "13/45/1984"),  # kept raw for the mapper to reject
    ({"field": "T", "datetime": "%d-%b-%y %H:%M"}, {"T": "14-MAR-23 08:15"}, "202303140815"),
    ({"field": "S", "map": {"1": "M"}}, {"S": "1"}, "M"),
    ({"field": "S", "map": {"1": "M"}}, {"S": "7"}, "7"),
    ({"field": "S", "map": {"1": "M"}, "map_default": ""}, {"S": "7"}, ""),
])
def test_field_expressions(expr, row, want):
    assert canonical.Evaluator(_Exp({})).value(expr, row) == want


@pytest.mark.parametrize("code,system,want", [
    ("E119", "I10", "E11.9"), ("J45909", "I10", "J45.909"), ("I10", "I10", "I10"), ("M545", "I10", "M54.5"),
    ("25000", "I9", "250.00"), ("4019", "I9", "401.9"), ("496", "I9", "496"), ("E8889", "I9", "E888.9"),
    ("V5861", "I9", "V58.61"), ("E11.9", "I10", "E11.9"),
])
def test_icd_decimal_reinsertion(code, system, want):
    expr = {"field": "C", "icd_decimal": {"system_field": "SYS", "icd9": "I9"}}
    assert canonical.Evaluator(_Exp({})).value(expr, {"C": code, "SYS": system}) == want


def test_lookup_expression():
    ev = canonical.Evaluator(_Exp({"TESTDICT": [{"TEST_CD": "K", "TEST_NAME": "POTASSIUM"}]}))
    expr = {"field": "T", "lookup": {"file": "TESTDICT", "key": "TEST_CD", "value": "TEST_NAME"}}
    assert ev.value(expr, {"T": "K"}) == "POTASSIUM" and ev.value(expr, {"T": "ZZ"}) == ""


def test_exclusion_is_staged_with_a_reason_not_dropped_silently():
    m = {"exclude": {"RESULT_STATUS": ["X"]}, "exclude_reason": {"X": "cancelled"}}
    assert "cancelled" in canonical._excluded(m, {"RESULT_STATUS": "X"})
    assert canonical._excluded(m, {"RESULT_STATUS": "F"}) is None


def _binding(fmt=None):
    return {"format": fmt or {"delimiter": "|", "encoding": "latin-1", "suffix": ".DAT"}}


def test_delimited_reader_is_strict(tmp_path):
    (tmp_path / "A.DAT").write_bytes(b"K|V\r\n1|x\r\n2|y|extra\r\n")
    with pytest.raises(ValueError, match="cells"):
        canonical.DelimitedExport(tmp_path, _binding()).rows("A")
    (tmp_path / "A.DAT").write_bytes(b"K|V\r\n1|x\r\n")
    (tmp_path / "manifest.json").write_text(json.dumps({"counts": {"A": 2}}))
    with pytest.raises(ValueError, match="manifest"):
        canonical.DelimitedExport(tmp_path, _binding()).rows("A")
    with pytest.raises(FileNotFoundError):
        canonical.DelimitedExport(tmp_path, _binding()).rows("B")
    with pytest.raises(ValueError, match="delimiter"):
        canonical.DelimitedExport(tmp_path, {"format": {}})


def test_profiler_reads_delimited_files_and_value_distributions(tmp_path):
    (tmp_path / "P.DAT").write_bytes("ID|SEX\r\n1|1\r\n2|3\r\n3|9\r\n4|PEÑA\r\n".encode("latin-1"))
    report = profile_export(tmp_path, delimited={"delimiter": "|", "encoding": "latin-1", "suffix": ".dat"},
                            code_value_limit=5)
    sex = report["files"]["P.DAT"]["fields"]["SEX"]
    assert sex["value_counts"] == {"1": 1, "3": 1, "9": 1, "PEÑA": 1}
    assert "value_counts" not in profile_export(tmp_path, delimited={"delimiter": "|", "encoding": "latin-1",
                                                                     "suffix": ".dat"})["files"]["P.DAT"]["fields"]["SEX"]


def test_overlay_terminology_layers_source_codes_over_the_base():
    t = OverlayTerminology({"labs": {"GLUC": "2345-7", "NEW": "9999-9"}, "race": {"Hispanic or Latino": "|hispanic-latino"},
                            "visit_class": {"TH": "virtual"}, "formulary": {"MD0105": "285018"}})
    assert t.labs["GLUC"] == ("2345-7", "mg/dL", "Glucose")   # house unit for a known LOINC
    assert t.labs["NEW"] == ("9999-9", "", "")
    assert t.labs["GLU"] == TERMS.labs["GLU"]                  # base rows still there
    assert t.race["hispanic or latino"] == (None, "hispanic-latino")
    assert t.visit_class["TH"] == "virtual" and t.formulary["MD0105"][0] == "285018"
    assert terms_for(object()) is TERMS
