from datetime import datetime

from bridge.extract.hl7 import parse_message
from bridge.mapping.identity import resolve, score_pair
from bridge.normalize.legacy import fix_mojibake, parse_crammed_address
from bridge.normalize.time import localize, parse_local


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


def test_legacy_helpers():
    assert fix_mojibake("JosÃ©") == ("José", True)
    assert fix_mojibake("Jose") == ("Jose", False)
    c = parse_crammed_address("12 OAK AVE APT 4 SPRINGFIELD IL 62701", {"SPRINGFIELD"})
    assert c.lines == ["12 OAK AVE", "APT 4"] and c.city == "Springfield" and c.state == "IL" and c.postal_code == "62701"
    c2 = parse_crammed_address("9 MAIN ST NORTH RIVERBEND IL 61842", {"RIVERBEND", "NORTH RIVERBEND"})
    assert c2.city == "North Riverbend"
    assert parse_crammed_address("nonsense") is None


def test_dst_flags():
    amb, flag = localize(datetime(2020, 11, 1, 1, 30), "America/Chicago")
    assert flag == "ambiguous" and amb.utcoffset().total_seconds() == -5 * 3600
    gap, flag = localize(datetime(2021, 3, 14, 2, 30), "America/Chicago")
    assert flag == "nonexistent"
    ok, flag = localize(datetime(2021, 6, 1, 9, 0), "America/Denver")
    assert flag is None and ok.utcoffset().total_seconds() == -6 * 3600


def test_hl7_basic():
    m = parse_message("MSH|^~\\&|A|B|C|D|202001011200||SIU^S15|X1|P|2.3\rSCH|AP1||||||F/U||||^^20^202701131400||||||||||||||Cancelled")
    assert m.type == "SIU^S15" and m.get("SCH-25") == "Cancelled" and m.get("SCH-11.4") == "202701131400"


def test_parse_local_reads_minutes_and_seconds_by_length():
    assert parse_local("202103151230") == datetime(2021, 3, 15, 12, 30)  # was 12:03:00
    assert parse_local("202103152359") == datetime(2021, 3, 15, 23, 59)  # was 23:05:09
    assert parse_local("20210315235945") == datetime(2021, 3, 15, 23, 59, 45)
    assert parse_local(" 20210315 ") == datetime(2021, 3, 15)
    for bad in (None, "", "2021031512", "2021031512300", "20210230", "2021-03-15", "202103152460"):
        assert parse_local(bad) is None, bad
