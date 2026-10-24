from datetime import date
import pytest
from bridge.normalize.demographics import parse_name, normalize_phone, parse_address, parse_legacy_date, Name, Address, DateParse

@pytest.mark.parametrize(("source", "family", "given", "suffix"), [
    ("SMITH, JOHN Q MD", "Smith", ["John","Q"], ["MD"]),
    ("O'NEIL, MARY-JO", "O'Neil", ["Mary-Jo"], []),
    ("DE LA CRUZ,JOSE A JR", "de la Cruz", ["Jose", "A"], ["JR"]),
    ("MCDONALD, AMY", "McDonald", ["Amy"], []),
    ("VAN DYKE, JOHN", "van Dyke", ["John"], []),
    ("LEE, ANN", "Lee", ["Ann"], []), ("DOE, JANE", "Doe", ["Jane"], []),
    ("SMITH, JOHN MD PHD", "Smith", ["John"], ["MD", "PHD"]),
    ("BROWN, ALICE II", "Brown", ["Alice"], ["II"]),
    ("", "", [], []), ("DOE,", "Doe", [], []),
    ("O'BRIEN, LIAM", "O'Brien", ["Liam"], []),
])
def test_names(source, family, given, suffix):
    assert parse_name(source) == Name(family, given, suffix)

@pytest.mark.parametrize(("source", "expected"), [
    ("(555) 123-4567", "+15551234567"), ("555.123.4567", "+15551234567"),
    ("5551234567x22", "+15551234567"), ("5551234567 ext. 23", "+15551234567"),
    ("+1 555 123 4567", "+15551234567"), ("1-555-123-4567", "+15551234567"),
    ("555 123 4567", "+15551234567"), ("5551234567", "+15551234567"),
    ("123-4567", None), ("", None), ("1234567890", "+11234567890"),
    ("0123456789", None), ("5550234567", None), ("abc5551234567", None),
])
def test_phone(source, expected):
    assert normalize_phone(source) == expected

@pytest.mark.parametrize(("source", "expected"), [
    ("123 MAIN ST^APT 4^SPRINGFIELD^IL^62701", Address(["123 MAIN ST","APT 4"],"Springfield","IL","62701")),
    ("123 Main St^^Madison^WI^53703", Address(["123 Main St"],"Madison","WI","53703")),
    ("123 Main St^Madison WI 53703", Address(["123 Main St"],"Madison","WI","53703")),
    ("123 Main St^^Madison WI 53703", Address(["123 Main St"],"Madison","WI","53703")),
    ("123 Main St^^Madison^WI 53703", Address(["123 Main St"],"Madison","WI","53703")),
    ("123 Main St", Address(["123 Main St"],"","","")),
    ("", Address([],"","","")),
])
def test_addresses(source, expected):
    assert parse_address(source) == expected

@pytest.mark.parametrize(("raw", "expected"), [
    ("19840312", DateParse(date(1984,3,12),"day",False)),
    ("1984-03-12", DateParse(date(1984,3,12),"day",False)),
    ("031284", DateParse(date(1984,3,12),"day",True)),
    ("031225", DateParse(date(2025,3,12),"day",True)),
    ("031227", DateParse(date(1927,3,12),"day",True)),
    ("00000000", DateParse(None,None,False)),
    ("", DateParse(None,None,False)),
    ("20230229", DateParse(None,None,False)),
    ("20240229", DateParse(date(2024,2,29),"day",False)),
    ("1984", DateParse(date(1984,1,1),"year",True)),
    ("foobar", DateParse(None,None,False)),
    ("20241301", DateParse(None,None,False)),
])
def test_dates(raw, expected):
    assert parse_legacy_date(raw, as_of=date(2026,10,24)) == expected
