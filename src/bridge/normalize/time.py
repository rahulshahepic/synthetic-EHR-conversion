"""Zone-less legacy timestamps -> zoned datetimes, flagging DST ambiguity."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_local(raw: str | None) -> datetime | None:
    raw = (raw or "").strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def localize(naive: datetime, tz: str) -> tuple[datetime, str | None]:
    """Attach a zone. Returns (aware datetime, flag) where flag is None, 'ambiguous' (fall-back hour,
    first occurrence chosen) or 'nonexistent' (spring-forward gap, shifted forward)."""
    z = ZoneInfo(tz)
    a, b = naive.replace(tzinfo=z, fold=0), naive.replace(tzinfo=z, fold=1)
    if a.utcoffset() != b.utcoffset():
        roundtrip = a.astimezone(timezone.utc).astimezone(z).replace(tzinfo=None)
        if roundtrip != naive:
            return (naive + timedelta(hours=1)).replace(tzinfo=z), "nonexistent"
        return a, "ambiguous"
    return a, None


def parse_date8(raw: str | None) -> date | None:
    try:
        return datetime.strptime((raw or "").strip(), "%Y%m%d").date()
    except ValueError:
        return None
