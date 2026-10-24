"""Halcyon-specific clean-up helpers that sit alongside the generic normalizers."""
from __future__ import annotations

import re

from .demographics import Address


def fix_mojibake(s: str) -> tuple[str, bool]:
    """Undo UTF-8 bytes that were decoded as latin-1 ('JosÃ©' -> 'José')."""
    if not re.search(r"[ÃÂ][\x80-\xbf]", s):
        return s, False
    try:
        return s.encode("latin-1").decode("utf-8"), True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s, False


_CRAMMED = re.compile(r"^(.*?)\s+([A-Z][A-Z .']+?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$")


def parse_crammed_address(raw: str, known_cities: set[str] | None = None) -> Address | None:
    """'12 OAK AVE APT 4 SPRINGFIELD IL 62701' -> Address. The street/city boundary is a guess
    unless the city is in `known_cities`; callers should mark the result as inferred."""
    s = raw.strip().upper()
    for city in sorted(known_cities or (), key=len, reverse=True):
        m = re.match(rf"^(.*?)\s+{re.escape(city)}\s+([A-Z]{{2}})\s+(\d{{5}}(?:-\d{{4}})?)$", s)
        if m:
            return _split(m.group(1), city, m.group(2), m.group(3))
    m = _CRAMMED.match(s)
    return _split(m.group(1), m.group(2), m.group(3), m.group(4)) if m else None


def _split(street: str, city: str, state: str, zip_: str) -> Address:
    apt = re.search(r"\s+((?:APT|UNIT|STE|#)\s*\S+)$", street)
    lines = [street[:apt.start()], apt.group(1)] if apt else [street]
    return Address(lines, city.title(), state, zip_)
