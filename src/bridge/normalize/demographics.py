"""Demographic normalizers (v0; see TASKS.md T-104 for the hardened version's spec)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

CREDENTIALS = {"MD", "DO", "NP", "PA", "PA-C", "RN", "FNP", "DDS", "PHD", "JR", "SR", "II", "III", "IV"}
LOWER_PARTICLES = {"de", "la", "del", "van", "von", "der", "da", "di"}


@dataclass
class Name:
    family: str
    given: list[str] = field(default_factory=list)
    suffix: list[str] = field(default_factory=list)


@dataclass
class Address:
    lines: list[str]
    city: str | None
    state: str | None
    postal_code: str | None
    crammed: bool = False


@dataclass
class DateParse:
    value: date | None
    precision: str | None
    inferred: bool = False


def fix_mojibake(s: str) -> tuple[str, bool]:
    """Undo UTF-8 bytes that were decoded as latin-1 ('JosÃ©' -> 'José')."""
    if not re.search(r"[ÃÂ][\x80-\xbf]", s):
        return s, False
    try:
        return s.encode("latin-1").decode("utf-8"), True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s, False


def smart_title(word: str) -> str:
    def one(part: str) -> str:
        low = part.lower()
        if low in LOWER_PARTICLES:
            return low
        if low.startswith("mc") and len(low) > 2:
            return "Mc" + low[2:].capitalize()
        if low.startswith("o'") and len(low) > 2:
            return "O'" + low[2:].capitalize()
        return low.capitalize()
    out = " ".join(one(p) for p in word.split())
    out = "-".join(seg[:1].upper() + seg[1:] if i else seg for i, seg in enumerate(out.split("-")))
    return out[:1].upper() + out[1:] if out else out


def parse_name(raw: str) -> Name:
    raw = raw.strip()
    family, _, rest = raw.partition(",")
    tokens = rest.replace(".", " ").split()
    suffix = []
    while tokens and tokens[-1].upper() in CREDENTIALS:
        suffix.insert(0, tokens.pop().upper())
    return Name(family=smart_title(family.strip()), given=[smart_title(t) for t in tokens], suffix=suffix)


def normalize_phone(raw: str | None) -> tuple[str | None, bool]:
    """Return (E.164 or None, extension_dropped)."""
    if not raw:
        return None, False
    ext = bool(re.search(r"x\d+$", raw, re.I))
    digits = re.sub(r"\D", "", re.sub(r"x\d+$", "", raw, flags=re.I))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01":
        return None, ext
    return "+1" + digits, ext


def parse_address(raw: str | None) -> Address | None:
    if not raw or not raw.strip("^ "):
        return None
    if "^" in raw:
        parts = (raw.split("^") + [""] * 5)[:5]
        return Address([p.strip() for p in parts[:2] if p.strip()], parts[2].strip().title() or None,
                       parts[3].strip().upper() or None, parts[4].strip() or None)
    m = re.match(r"^(.*?)\s+([A-Z][A-Z .']+?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", raw.strip())
    if not m:
        return Address([raw.strip()], None, None, None, crammed=True)
    street = m.group(1)
    apt = re.search(r"\s+((?:APT|UNIT|STE|#)\s*\S+)$", street)
    lines = [street[:apt.start()], apt.group(1)] if apt else [street]
    return Address(lines, m.group(2).title(), m.group(3), m.group(4), crammed=True)


def parse_legacy_date(raw: str | None, as_of: date) -> DateParse:
    raw = (raw or "").strip()
    if not raw or set(raw) == {"0"}:
        return DateParse(None, None)
    try:
        if re.fullmatch(r"\d{8}", raw):
            return DateParse(date(int(raw[:4]), int(raw[4:6]), int(raw[6:])), "day")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return DateParse(date.fromisoformat(raw), "day")
        if re.fullmatch(r"\d{6}", raw):  # MMDDYY
            yy = int(raw[4:])
            year = 2000 + yy if 2000 + yy <= as_of.year else 1900 + yy
            return DateParse(date(year, int(raw[:2]), int(raw[2:4])), "day", inferred=True)
    except ValueError:
        return DateParse(None, None)
    return DateParse(None, None)
