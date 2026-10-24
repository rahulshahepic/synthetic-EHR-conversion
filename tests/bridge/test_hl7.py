"""Tests for the HL7 v2 parser (T-101). All messages are synthetic."""
import pytest

from bridge.extract.hl7 import iter_messages, parse_message

ADT_A08 = "\r".join([
    r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151030||ADT^A08|MSG0000123|P|2.3",
    "EVN|A08|202401151030",
    "PID|1||123456^^^FAC1^MR||DOE^JANE^Q||19840312|F|||"
    "123 MAIN ST^^SPRINGFIELD^IL^62701||5551234567",
    "PV1|1|O|FAC1",
])

ORU_R01 = "\r".join([
    r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151200||ORU^R01|MSG0000456|P|2.3",
    "PID|1||123456^^^FAC1^MR||DOE^JANE^Q||19840312|F",
    "OBR|1||ACC123|GLU^GLUCOSE^L",
    "OBX|1|NM|GLU^GLUCOSE^L||95|mg/dl|70-100|N|||F",
    "OBX|2|NM|K^POTASSIUM^L||4.2|MEQ/L|3.5-5.1|N|||F",
    "OBX|3|ST|NOTE^COMMENT^L||see note||||||F",
])


# ---------------------------------------------------------------- basics

def test_message_type_and_control_id():
    msg = parse_message(ADT_A08)
    assert msg.type == "ADT^A08"
    assert msg.control_id == "MSG0000123"


def test_segments_in_order():
    msg = parse_message(ADT_A08)
    assert [s.name for s in msg.segments] == ["MSH", "EVN", "PID", "PV1"]


def test_get_field_and_components():
    msg = parse_message(ADT_A08)
    assert msg.get("PID-3") == "123456^^^FAC1^MR"
    assert msg.get("PID-3.1") == "123456"
    assert msg.get("PID-3.4") == "FAC1"
    assert msg.get("PID-3.5") == "MR"
    assert msg.get("PID-5.1") == "DOE"
    assert msg.get("PID-5.2") == "JANE"
    assert msg.get("PID-5.3") == "Q"
    assert msg.get("PID-7") == "19840312"
    assert msg.get("PID-11.3") == "SPRINGFIELD"
    assert msg.get("PID-11.5") == "62701"
    assert msg.get("PID-13") == "5551234567"


def test_msh_fields_use_hl7_numbering():
    msg = parse_message(ADT_A08)
    assert msg.get("MSH-1") == "|"
    assert msg.get("MSH-2") == r"^~\&"
    assert msg.get("MSH-3") == "HALCYON"
    assert msg.get("MSH-9") == msg.type
    assert msg.get("MSH-10") == msg.control_id


def test_present_empty_vs_absent():
    msg = parse_message(ADT_A08)
    assert msg.get("PID-2") == ""        # present, empty
    assert msg.get("PID-5.4") is None    # component beyond the value
    assert msg.get("PID-14") is None     # field beyond the segment
    assert msg.get("ZZZ-1") is None      # no such segment
    assert msg.get_all("ZZZ-1") == []


def test_missing_trailing_fields_tolerated():
    msg = parse_message("PID|1||123456")
    assert msg.get("PID-3") == "123456"
    assert msg.get("PID-5") is None
    assert msg.get("PID-5.1") is None


def test_trailing_separators_tolerated():
    msg = parse_message("PID|1||123456|||")
    assert msg.get("PID-3") == "123456"
    assert msg.get("PID-4") == ""
    assert msg.get("PID-6") == ""
    assert msg.get("PID-7") is None


def test_line_endings_equivalent():
    parsed = []
    for sep in ("\r", "\n", "\r\n"):
        msg = parse_message(ADT_A08.replace("\r", sep))
        parsed.append([(s.name, s.fields) for s in msg.segments])
    assert parsed[0] == parsed[1] == parsed[2]


def test_empty_text_parses_to_empty_message():
    for text in ("", "  \n\r\n ", "\r\r"):
        msg = parse_message(text)
        assert msg.segments == []
        assert msg.type is None
        assert msg.control_id is None


def test_message_without_msh_uses_defaults():
    msg = parse_message("PID|1||123456||DOE^JANE")
    assert msg.type is None
    assert msg.control_id is None
    assert msg.get("PID-5.1") == "DOE"
    assert msg.encoding.field_separator == "|"


# ------------------------------------------------------- repeated segments

def test_get_with_seg_index():
    msg = parse_message(ORU_R01)
    assert msg.get("OBX-5") == "95"  # default: first OBX
    assert msg.get("OBX-5", seg_index=0) == "95"
    assert msg.get("OBX-5", seg_index=1) == "4.2"
    assert msg.get("OBX-5", seg_index=2) == "see note"
    assert msg.get("OBX-3.1", seg_index=1) == "K"
    assert msg.get("OBX-6", seg_index=0) == "mg/dl"


def test_seg_index_out_of_range():
    msg = parse_message(ORU_R01)
    assert msg.get("OBX-5", seg_index=7) is None
    assert msg.get_all("OBX-5", seg_index=7) == []
    assert msg.segment("OBX", 7) is None
    assert msg.segment("ZZZ") is None


def test_segment_object_api():
    msg = parse_message(ORU_R01)
    obx = msg.segment("OBX", 1)
    assert obx is not None
    assert obx.name == "OBX"
    assert obx.get(5) == "4.2"
    assert obx.get(3, 2) == "POTASSIUM"
    assert obx.get_all(3) == ["K^POTASSIUM^L"]
    assert obx.get_all(3, 2) == ["POTASSIUM"]


# ------------------------------------------------------------ repetitions

REPETITIONS = "\r".join([
    r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151030||ADT^A04|MSG0000777|P|2.3",
    "PID|1||123456^^^FAC1^MR~789012^^^FAC2||DOE^JANE^Q||19840312|F|||||"
    "5551234567~5559876543",
])


def test_get_returns_first_repetition():
    msg = parse_message(REPETITIONS)
    assert msg.get("PID-3") == "123456^^^FAC1^MR"
    assert msg.get("PID-13") == "5551234567"


def test_get_all_repetitions():
    msg = parse_message(REPETITIONS)
    assert msg.get_all("PID-3") == ["123456^^^FAC1^MR", "789012^^^FAC2"]
    assert msg.get_all("PID-13") == ["5551234567", "5559876543"]


def test_get_all_component_across_repetitions():
    msg = parse_message(REPETITIONS)
    assert msg.get_all("PID-3.1") == ["123456", "789012"]
    assert msg.get_all("PID-3.4") == ["FAC1", "FAC2"]
    # Second repetition has no 5th component: position kept, value "".
    assert msg.get_all("PID-3.5") == ["MR", ""]


# ------------------------------------------------------------ subcomponents

def test_subcomponents_and_z_segment():
    text = "\r".join([
        r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151030||ADT^A08|MSG1|P|2.3",
        "ZPI|1|ABC&DEF^GHI|ZZZ",
    ])
    msg = parse_message(text)
    assert msg.get("ZPI-2") == "ABC&DEF^GHI"
    assert msg.get("ZPI-2.1") == "ABC&DEF"
    assert msg.get("ZPI-2.1.1") == "ABC"
    assert msg.get("ZPI-2.1.2") == "DEF"
    assert msg.get("ZPI-2.1.3") is None
    assert msg.get("ZPI-2.2") == "GHI"
    assert msg.get("ZPI-3") == "ZZZ"


# ---------------------------------------------------------------- escapes

@pytest.mark.parametrize(("raw", "expected"), [
    (r"a\F\b", "a|b"),
    (r"a\S\b", "a^b"),
    (r"a\T\b", "a&b"),
    (r"a\R\b", "a~b"),
    (r"a\E\b", "a\\b"),
    (r"a\.br\b", "a\nb"),
    (r"a\f\b", "a|b"),       # case-insensitive, lenient receiver
    (r"a\Z99\b", r"a\Z99\b"),  # unknown sequence passes through
    ("plain", "plain"),
])
def test_unescape(raw, expected):
    msg = parse_message(f"MSH|^~\\&|H|F|B|N|20240101||ADT^A08|M1|P|2.3\rNTE|1||{raw}")
    assert msg.get("NTE-3") == expected


def test_escaped_separator_does_not_split():
    text = "\r".join([
        r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151200||ORU^R01|MSG2|P|2.3",
        r"OBX|1|ST|X^Y||a\F\b^c",
    ])
    msg = parse_message(text)
    assert msg.get("OBX-5") == "a|b^c"     # whole field, unescaped
    assert msg.get("OBX-5.1") == "a|b"     # \F\ did not split the field
    assert msg.get("OBX-5.2") == "c"       # the real ^ did split components
    assert msg.get_all("OBX-5") == ["a|b^c"]


def test_escaped_repetition_does_not_split():
    text = "\r".join([
        r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151200||ORU^R01|MSG3|P|2.3",
        r"OBX|1|ST|X^Y||x\R\y",
    ])
    msg = parse_message(text)
    assert msg.get_all("OBX-5") == ["x~y"]


# ------------------------------------------------------ nonstandard MSH-2

EXOTIC = "\n".join([
    r"MSH*$%!#*HALCYON*RIVERBEND*BRIDGE*NIMBUS*202401151030**ADT$A08*MSG77*P*2.3",
    "PID*1**999$$$FAC9$MR**DOE$JANE",
    "NTE*1**one%two",
])


def test_nonstandard_separators_honored():
    msg = parse_message(EXOTIC)
    assert msg.type == "ADT$A08"
    assert msg.control_id == "MSG77"
    assert msg.get("MSH-1") == "*"
    assert msg.get("MSH-2") == "$%!#"
    assert msg.get("PID-5.1") == "DOE"
    assert msg.get("PID-5.2") == "JANE"
    assert msg.get("PID-3.5") == "MR"
    assert msg.get_all("NTE-3") == ["one", "two"]  # % is the repetition sep


def test_nonstandard_escape_character_honored():
    text = "\n".join([
        r"MSH*$%!#*HALCYON*RIVERBEND*BRIDGE*NIMBUS*202401151030**ADT$A08*MSG78*P*2.3",
        "NTE*1**value with !F! and !S! and !E! inside",
    ])
    msg = parse_message(text)
    # \F\ -> the message's field sep (*), \S\ -> its component sep ($).
    assert msg.get("NTE-3") == "value with * and $ and ! inside"


def test_partial_msh2_falls_back_to_defaults():
    text = "\r".join([
        r"MSH|^~|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151030||ADT^A01|MSG9|P|2.3",
        r"NTE|1||a\F\b&C",
    ])
    msg = parse_message(text)
    assert msg.encoding.escape_character == "\\"
    assert msg.encoding.subcomponent_separator == "&"
    assert msg.get("NTE-3") == "a|b&C"
    assert msg.get("NTE-3.1.1") == "a|b"
    assert msg.get("NTE-3.1.2") == "C"


# ------------------------------------------------------------ iter_messages

def _write(tmp_path, name, data):
    path = tmp_path / name
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def test_iter_messages_blank_line_separated(tmp_path):
    path = _write(tmp_path, "adt.hl7", ADT_A08 + "\n\n" + ORU_R01 + "\n")
    msgs = list(iter_messages(path))
    assert [m.type for m in msgs] == ["ADT^A08", "ORU^R01"]
    assert [m.control_id for m in msgs] == ["MSG0000123", "MSG0000456"]


def test_iter_messages_crlf_without_blank_lines(tmp_path):
    text = ADT_A08.replace("\r", "\r\n") + "\r\n" + ORU_R01.replace("\r", "\r\n")
    msgs = list(iter_messages(_write(tmp_path, "feed.hl7", text)))
    assert [m.type for m in msgs] == ["ADT^A08", "ORU^R01"]


def test_iter_messages_cr_only(tmp_path):
    text = ADT_A08 + "\r" + ORU_R01  # segments and messages all \r-separated
    msgs = list(iter_messages(_write(tmp_path, "feed.hl7", text)))
    assert len(msgs) == 2
    assert msgs[1].get("OBX-5", seg_index=1) == "4.2"


def test_iter_messages_lf_only(tmp_path):
    text = ADT_A08.replace("\r", "\n") + "\n" + ORU_R01.replace("\r", "\n")
    msgs = list(iter_messages(_write(tmp_path, "feed.hl7", text)))
    assert [m.type for m in msgs] == ["ADT^A08", "ORU^R01"]


def test_iter_messages_is_an_iterator(tmp_path):
    path = _write(tmp_path, "feed.hl7", ADT_A08)
    it = iter_messages(path)
    assert next(it).type == "ADT^A08"
    with pytest.raises(StopIteration):
        next(it)


def test_iter_messages_empty_and_blank_files(tmp_path):
    assert list(iter_messages(_write(tmp_path, "a.hl7", ""))) == []
    assert list(iter_messages(_write(tmp_path, "b.hl7", "\n\n\r\n  \n"))) == []


def test_iter_messages_latin1_fallback(tmp_path):
    raw = b"\r".join([
        rb"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151030||ADT^A04|MSG1|P|2.3",
        b"PID|1||123||MU\xd1OZ^JOS\xc9||19840312|M",  # MUÑOZ^JOSÉ in latin-1
    ])
    msgs = list(iter_messages(_write(tmp_path, "latin.hl7", raw)))
    assert len(msgs) == 1
    assert msgs[0].get("PID-5.1") == "MUÑOZ"
    assert msgs[0].get("PID-5.2") == "JOSÉ"


def test_iter_messages_utf8_preferred_over_latin1(tmp_path):
    text = "\r".join([
        r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151030||ADT^A04|MSG1|P|2.3",
        "PID|1||123||MUÑOZ^JOSÉ||19840312|M",
    ])
    msgs = list(iter_messages(_write(tmp_path, "utf8.hl7", text.encode("utf-8"))))
    assert msgs[0].get("PID-5.1") == "MUÑOZ"
    assert msgs[0].get("PID-5.2") == "JOSÉ"


def test_parse_message_accepts_bytes_with_latin1(tmp_path):
    raw = b"PID|1||123||MU\xd1OZ^JOS\xc9"
    msg = parse_message(raw)
    assert msg.get("PID-5.1") == "MUÑOZ"


# ------------------------------------------------------------------- misc

def test_merge_message_mrg_segment():
    text = "\r".join([
        r"MSH|^~\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|202401151030||ADT^A40|MSG0000999|P|2.3",
        "EVN|A40|202401151030",
        "PID|1||123456^^^FAC1^MR||DOE^JANE^Q||19840312|F",
        "MRG|654321^^^FAC1^MR",
    ])
    msg = parse_message(text)
    assert msg.type == "ADT^A40"
    assert msg.get("MRG-1.1") == "654321"
    assert msg.get("PID-3.1") == "123456"


@pytest.mark.parametrize("bad", [
    "PID", "PID-", "PID-X", "P-1", "PID-5.", "PID-5.1.2.3", "PID_5", "",
])
def test_invalid_path_raises(bad):
    msg = parse_message(ADT_A08)
    with pytest.raises(ValueError):
        msg.get(bad)
    with pytest.raises(ValueError):
        msg.get_all(bad)


def test_subcomponent_without_component_raises():
    msg = parse_message(ADT_A08)
    pid = msg.segment("PID")
    assert pid is not None
    with pytest.raises(ValueError):
        pid.get(5, None, 1)
