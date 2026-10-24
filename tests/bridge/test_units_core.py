from datetime import date, datetime

from bridge.extract.hl7 import parse_message
from bridge.mapping.identity import resolve, score_pair
from bridge.normalize import demographics as d
from bridge.normalize.time import localize


def pat(pid, name, dob="19800101", ssn="1234"):
    return {"PAT_ID": pid, "PAT_NAME": name, "DOB": dob, "SSN4": ssn}


def test_identity_exact_links_and_typo_goes_to_review():
    pats = [pat("P1", "SMITH,JOHN"), pat("P2", "SMITH,JOHN"), pat("P3", "SMIHT,JOHN"), pat("P4", "DOE,JANE", "19700101", "9999")]
    clusters, review, reasons = resolve(pats, [])
    assert sorted(clusters["P1"]) == ["P1", "P2"] and reasons["P2"] == "deterministic"
    assert len(review) == 1 and review[0].b == "P3"
    assert clusters["P4"] == ["P4"]


def test_identity_a40_merge_is_authoritative():
    pats = [pat("P1", "SMITH,JOHN"), pat("P2", "JONES,BOB", "19900101", "1111")]
    clusters, review, reasons = resolve(pats, [("P1", "P2")])
    assert sorted(clusters["P1"]) == ["P1", "P2"] and reasons["P2"] == "adt_a40"


def test_score_nickname_and_mojibake():
    assert "first~" in score_pair(pat("A", "SMITH,ROBERT"), pat("B", "SMITH,BOB")).reasons
    assert score_pair(pat("A", "NUÃ\x91EZ,JOSÃ\x89"), pat("B", "NUÑEZ,JOSÉ")).score == 1.0


def test_names():
    n = d.parse_name("DE LA CRUZ,JOSE A JR")
    assert n.family == "De la Cruz" and n.given == ["Jose", "A"] and n.suffix == ["JR"]
    assert d.parse_name("O'NEIL, MARY-JO").family == "O'Neil"
    assert d.parse_name("MCDONALD, JOHN Q MD").suffix == ["MD"]
    assert d.fix_mojibake("JosÃ©") == ("José", True)


def test_phone_address_dates():
    assert d.normalize_phone("(312) 555-1234") == ("+13125551234", False)
    assert d.normalize_phone("3125551234x22") == ("+13125551234", True)
    assert d.normalize_phone("555-1234") == (None, False)
    a = d.parse_address("12 OAK AVE^APT 4^SPRINGFIELD^IL^62701")
    assert a.lines == ["12 OAK AVE", "APT 4"] and a.city == "Springfield" and a.state == "IL"
    c = d.parse_address("12 OAK AVE APT 4 SPRINGFIELD IL 62701")
    assert c.crammed and c.state == "IL" and c.postal_code == "62701"
    as_of = date(2026, 9, 30)
    assert d.parse_legacy_date("19840312", as_of).value == date(1984, 3, 12)
    p = d.parse_legacy_date("031284", as_of)
    assert p.value == date(1984, 3, 12) and p.inferred
    assert d.parse_legacy_date("031225", as_of).value == date(2025, 3, 12)
    assert d.parse_legacy_date("00000000", as_of).value is None


def test_dst_flags():
    amb, flag = localize(datetime(2020, 11, 1, 1, 30), "America/Chicago")
    assert flag == "ambiguous" and amb.utcoffset().total_seconds() == -5 * 3600
    gap, flag = localize(datetime(2021, 3, 14, 2, 30), "America/Chicago")
    assert flag == "nonexistent"
    ok, flag = localize(datetime(2021, 6, 1, 9, 0), "America/Denver")
    assert flag is None and ok.utcoffset().total_seconds() == -6 * 3600


def test_hl7_basic():
    m = parse_message("MSH|^~\\&|A|B|C|D|202001011200||ADT^A08|X1|P|2.3\rPID|1||123^^^FAC1^MR||O\\S\\NEIL^ANN||19800101")
    assert m.type == "ADT^A08" and m.control_id == "X1"
    assert m.get("PID-3.4") == "FAC1" and m.get("PID-5.1") == "O^NEIL"
