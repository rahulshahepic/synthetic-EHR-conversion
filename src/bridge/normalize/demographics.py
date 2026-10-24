"""Conservative demographic normalization for synthetic legacy EHR extracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


@dataclass(frozen=True)
class Name:
    family: str
    given: list[str]
    suffix: list[str]


@dataclass(frozen=True)
class Address:
    lines: list[str]
    city: str
    state: str
    postal_code: str


@dataclass(frozen=True)
class DateParse:
    value: date | None
    precision: str | None
    inferred: bool


_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "DO", "PHD", "RN", "DDS", "DMD", "NP", "PA"}
_PARTICLES = {"de", "del", "de la", "van", "von", "da", "dos", "di", "la", "le"}
_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())


def _case(part: str, *, particle: bool = False) -> str:
    if not part:
        return part
    if particle and part.lower() in _PARTICLES:
        return part.lower()
    if "-" in part:
        return "-".join(_case(x) for x in part.split("-"))
    if "'" in part:
        return "'".join(_case(x) for x in part.split("'"))
    lower = part.lower()
    if lower.startswith("mc") and len(part) > 2:
        return "Mc" + part[2].upper() + part[3:].lower()
    return lower.capitalize()


def _name_words(text: str) -> list[str]:
    words = text.split()
    return [_case(w, particle=i < len(words) - 1) for i, w in enumerate(words)]


def parse_name(raw: str) -> Name:
    """Parse LAST,FIRST MIDDLE and common suffix/credential trailers."""
    if "," in raw:
        family, rest = raw.split(",", 1)
    else:
        words = raw.split()
        family, rest = (words[-1], " ".join(words[:-1])) if words else ("", "")
    names = rest.strip().split()
    suffix = []
    while names and names[-1].rstrip(".").upper() in _SUFFIXES:
        suffix.insert(0, names.pop().rstrip(".").upper())
    return Name(" ".join(_name_words(family.strip())), [_case(w) for w in names], suffix)


def normalize_phone(raw: str, default_region: str = "US") -> str | None:
    """US/Canada NANP numbers to E.164. Extensions discarded, not persisted."""
    if default_region.upper() not in {"US", "CA"}:
        return None
    core = re.split(r"(?i)(?:ext\.?|extension|x|#)\s*\d+\s*$", raw.strip(), maxsplit=1)[0]
    if re.search(r"[^\d\s()+.\-]", core):
        return None
    digits = re.sub(r"\D", "", core)
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01" or digits[3] in "01":
        return None
    return "+1" + digits


_CITY_STATE_ZIP = re.compile(r"^(.+?)[,\s]+([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$")
_STATE_ZIP = re.compile(r"^([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$")


def parse_address(raw: str) -> Address:
    """HL7 XAD-like caret fields, with limited packed US city/state/ZIP support."""
    fields = [v.strip() for v in raw.split("^")]
    while len(fields) < 5:
        fields.append("")
    line1, line2, city, state, postal = fields[:5]
    if not city and not state and not postal:
        packed = _CITY_STATE_ZIP.fullmatch(line2)
        if packed:
            line2, city, state, postal = "", *packed.groups()
    if city and not state and not postal:
        packed = _CITY_STATE_ZIP.fullmatch(city)
        if packed:
            city, state, postal = packed.groups()
        else:
            match = _STATE_ZIP.fullmatch(city)
            if match:
                city, state, postal = "", *match.groups()
    if state and not postal:
        match = _STATE_ZIP.fullmatch(state)
        if match:
            state, postal = match.groups()
    return Address([v for v in (line1, line2) if v], city.title(), state.upper(), postal)


def parse_legacy_date(raw: str, as_of: date | None = None) -> DateParse:
    """Legacy zero-dates are missing; YY uses latest nonfuture century.

    A two-digit year is interpreted as the latest year <= as_of.year with
    matching final two digits. For ambiguous values, inferred is True.
    """
    as_of = as_of or date.today()
    s = raw.strip()
    if not s or not s.strip("0-"):
        return DateParse(None, None, False)
    inferred = False
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if match:
        year, month, day = map(int, match.groups())
    elif re.fullmatch(r"\d{8}", s):
        year, month, day = int(s[:4]), int(s[4:6]), int(s[6:])
    elif re.fullmatch(r"\d{6}", s):
        month, day, yy = int(s[:2]), int(s[2:4]), int(s[4:])
        year = as_of.year - ((as_of.year - yy) % 100)
        inferred = True
    elif re.fullmatch(r"\d{4}", s):
        year, month, day = int(s), 1, 1
        try:
            return DateParse(date(year, month, day), "year", True)
        except ValueError:
            return DateParse(None, None, False)
    elif re.fullmatch(r"\d{6}", s):
        return DateParse(None, None, False)
    else:
        return DateParse(None, None, False)
    try:
        value = date(year, month, day)
    except ValueError:
        return DateParse(None, None, inferred)
    if value > as_of and inferred:
        year -= 100
        try:
            value = date(year, month, day)
        except ValueError:
            return DateParse(None, None, inferred)
    return DateParse(value, "day", inferred)
