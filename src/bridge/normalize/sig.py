"""Free-text medication sig parser for legacy prescriptions (all data synthetic).

Legacy sigs are terse Latin, half sentences, or both (``"1 tab po q4-6h prn
pain"``, ``"take one tablet by mouth twice daily"``). This parser extracts the
structured pieces Bridge's medication mapper needs and is deliberately
conservative: anything it cannot interpret lands in ``SigResult.unparsed``
instead of being guessed at, and the confidence score reflects that.

Conventions (the choices the TASKS.md spec leaves open):

- **Dose ranges** (``"1-2 tabs"``): ``dose_value`` takes the *lower* bound, as
  the spec directs. The original range token is also copied into ``unparsed``
  (e.g. ``"1-2"``) so the lost upper bound stays visible downstream; because a
  range is clinically material, confidence is capped below 0.5. The same
  treatment applies to interval frequency ranges (``"q4-6h"``): the period
  takes the *upper* bound (the longest allowed interval, 6 h) and the range
  token is noted in ``unparsed``.
- **`unparsed` only ever contains clinically material leftovers.** Timing
  annotations (``ac``, ``pc``, ``with meals``, ``with food``, ``before
  breakfast``), administration verbs (``take``, ``swish and spit``, ...), and
  the PRN reason are understood concepts with no dedicated field, so they are
  consumed silently. Everything else the parser cannot place is material by
  construction, which is what makes the confidence rule below hold.
- **Confidence** is deterministic: start at 1.0; an as-directed sig scores
  0.3; any material leftover in ``unparsed`` caps the score at 0.4; a sig
  with neither dose nor frequency structure scores 0.1 (0.0 for empty
  input); a missing dose or a missing frequency (when the other is present)
  subtracts 0.2.
- **As directed** (``ud``, ``as directed``, ``use as directed``) is
  understood, not a parse failure: it is consumed, leaves dose/frequency
  empty, and scores 0.3 because the structured result carries no dosing.
- **Frequencies**: ``bid`` -> count 2 per 1 d; ``q6h`` -> count 1 per 6 h;
  ``qhs``/``qam``/bedtime -> count 1 per 1 d; every-other-day -> count 1 per
  2 d. ``frequency_period`` is always a float.
- **Units**: the spec's UCUM-ish set plus ``ug`` for mcg/µg doses (UCUM's
  spelling), ``[iU]`` for "units", ``cc`` read as ``mL``, and teaspoon /
  tablespoon converted at 5 / 15 mL.
- **PRN reason** is the free text after ``prn`` / ``as needed`` once known
  items are removed, lowercased. Material leftovers *before* the ``prn``
  still land in ``unparsed``.

Durations stated in months are read as 30 days each (a documented
approximation). Deliberately unhandled (lands in ``unparsed``, confidence
< 0.5): tapers with actual dose steps, alternating-dose instructions
("1 tab Mon, 2 tabs Tue"), spaced intervals (``q 6 h``), routes outside the
spec's set (e.g. vaginal), and durations with no number ("for a while").
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

__all__ = ["SigResult", "parse_sig"]

Route = Literal[
    "oral", "iv", "im", "subcut", "topical", "inhaled", "rectal",
    "ophthalmic", "otic", "nasal", "transdermal", "sublingual",
]
PeriodUnit = Literal["h", "d", "wk"]


@dataclass(frozen=True)
class SigResult:
    dose_value: float | None
    dose_unit: str | None
    route: Route | None
    frequency_count: int | None
    frequency_period: float | None
    frequency_period_unit: PeriodUnit | None
    as_needed: bool
    as_needed_reason: str | None
    duration_days: int | None
    confidence: float
    unparsed: str


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

_NUMBER_WORDS = {
    "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
    "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0,
    "eleven": 11.0, "twelve": 12.0,
}

_FRACTION_CHARS = {"¼": "1/4", "½": "1/2", "¾": "3/4", "⅓": "1/3", "⅔": "2/3"}

# token (lowercase, punctuation-stripped) -> (UCUM-ish dose unit, multiplier)
_DOSE_UNITS: dict[str, tuple[str, float]] = {
    "tab": ("{tab}", 1.0), "tabs": ("{tab}", 1.0),
    "tablet": ("{tab}", 1.0), "tablets": ("{tab}", 1.0),
    "cap": ("{cap}", 1.0), "caps": ("{cap}", 1.0),
    "capsule": ("{cap}", 1.0), "capsules": ("{cap}", 1.0),
    "puff": ("{puff}", 1.0), "puffs": ("{puff}", 1.0),
    "drop": ("{drop}", 1.0), "drops": ("{drop}", 1.0),
    "gtt": ("{drop}", 1.0), "gtts": ("{drop}", 1.0),
    "unit": ("[iU]", 1.0), "units": ("[iU]", 1.0), "iu": ("[iU]", 1.0),
    "mg": ("mg", 1.0), "mcg": ("ug", 1.0), "µg": ("ug", 1.0), "ug": ("ug", 1.0),
    "ml": ("mL", 1.0), "cc": ("mL", 1.0),
    "tsp": ("mL", 5.0), "teaspoon": ("mL", 5.0), "teaspoons": ("mL", 5.0),
    "tbsp": ("mL", 15.0), "tablespoon": ("mL", 15.0), "tablespoons": ("mL", 15.0),
}

# single-token routes -> canonical route
_TOKEN_ROUTES: dict[str, Route] = {
    "po": "oral", "oral": "oral", "orally": "oral",
    "iv": "iv", "im": "im",
    "subq": "subcut", "sq": "subcut", "sc": "subcut", "subcut": "subcut",
    "subcutaneous": "subcut", "subcutaneously": "subcut",
    "inh": "inhaled", "inhaled": "inhaled", "inhalation": "inhaled",
    "topical": "topical", "topically": "topical",
    "rectal": "rectal", "rectally": "rectal", "pr": "rectal",
    "ophth": "ophthalmic", "ophthalmic": "ophthalmic",
    "otic": "otic",
    "nasal": "nasal", "intranasal": "nasal", "intranasally": "nasal",
    "transdermal": "transdermal", "transdermally": "transdermal",
    "sl": "sublingual", "sublingual": "sublingual", "sublingually": "sublingual",
}

# multi-word route phrases, matched on the normalized text before tokenizing
_PHRASE_ROUTES: list[tuple[re.Pattern[str], Route]] = [
    (re.compile(r"\bby mouth\b"), "oral"),
    (re.compile(r"\bunder the skin\b"), "subcut"),
    (re.compile(r"\bunder (?:the )?tongue\b"), "sublingual"),
    (re.compile(r"\bin (?:each|both|the (?:left|right)) (?:eye|eyes)\b"), "ophthalmic"),
    (re.compile(r"\bin (?:each|both|the (?:left|right)) (?:ear|ears)\b"), "otic"),
    (re.compile(r"\bin (?:each|both) nostrils?\b"), "nasal"),
    (re.compile(r"\bper rectum\b"), "rectal"),
    (re.compile(r"\binto the (?:left |right )?eye\b"), "ophthalmic"),
]

# single-token frequencies -> (count, period, period_unit)
_TOKEN_FREQS: dict[str, tuple[int, float, PeriodUnit]] = {
    "qd": (1, 1.0, "d"), "daily": (1, 1.0, "d"), "od": (1, 1.0, "d"),
    "bid": (2, 1.0, "d"), "tid": (3, 1.0, "d"), "qid": (4, 1.0, "d"),
    "qhs": (1, 1.0, "d"), "hs": (1, 1.0, "d"),
    "qam": (1, 1.0, "d"), "qpm": (1, 1.0, "d"), "qod": (1, 2.0, "d"),
}

# known-but-unmodeled timing annotations: consumed, no field, no penalty
_TIMING_TOKENS = {"ac", "pc"}
_TIMING_PHRASES = [
    re.compile(r"\bwith (?:meals?|food)\b"),
    re.compile(r"\bbefore (?:breakfast|meals?|food)\b"),
    re.compile(r"\bafter (?:meals?|food)\b"),
    re.compile(r"\bon an empty stomach\b"),
]

# filler / administration verbs: understood, carry no structured field
_FILLER_TOKENS = {
    "take", "use", "apply", "give", "inject", "inhale", "swish", "spit", "swallow",
    "instill", "insert", "place", "the", "a", "an", "and", "as", "per",
    "mouth", "by", "into", "in", "on", "to", "of", "for", "with", "x",
    "tablet", "tablets", "capsule", "capsules",  # only when unit-less leftovers
}

_AS_DIRECTED_PHRASES = [
    re.compile(r"\b(?:take|use|apply)?\s*as directed\b"),
    re.compile(r"\bas instructed\b"),
]
_AS_DIRECTED_TOKENS = {"ud", "u.d."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, expand unicode fractions, collapse whitespace."""
    out = []
    for ch in text:
        if ch in _FRACTION_CHARS:
            out.append(f" {_FRACTION_CHARS[ch]} ")
        else:
            out.append(ch)
    s = "".join(out).lower()
    # "1 1/2" from "1½": a digit directly before an inserted fraction is fine
    # as two tokens; the dose pass already sums integer + fraction tokens.
    return re.sub(r"\s+", " ", s).strip()


def _blank(text: str, span: tuple[int, int]) -> str:
    return text[: span[0]] + " " + text[span[1]:]


def _number(token: str) -> float | None:
    """Parse a plain number, fraction, or number word; None if not numeric."""
    if token in _NUMBER_WORDS:
        return _NUMBER_WORDS[token]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", token)
    if m:
        denom = float(m.group(2))
        return float(m.group(1)) / denom if denom else None
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    return None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_sig(text: str) -> SigResult:
    """Parse a free-text medication sig into a :class:`SigResult`.

    Never raises on sig *content*; raises ``TypeError`` for non-str input
    (a programmer error). See the module docstring for the conventions.
    """
    if not isinstance(text, str):
        raise TypeError(f"parse_sig expects str, got {type(text).__name__}")
    if not text.strip():
        return SigResult(None, None, None, None, None, None,
                         False, None, None, 0.0, "")

    work = _normalize(text)
    as_directed = False
    duration_days: int | None = None
    route: Route | None = None
    freq: tuple[int, float, PeriodUnit] | None = None
    range_notes: list[str] = []

    # -- as directed ------------------------------------------------------
    for pat in _AS_DIRECTED_PHRASES:
        m = pat.search(work)
        if m:
            as_directed = True
            work = _blank(work, m.span())

    # -- duration: "x10d", "x 10 days", "for 2 weeks", "for 1 month" -----
    dur = re.search(
        r"(?:\bx\s*|for\s+)(\d+(?:\.\d+)?)\s*(d|days?|wks?|weeks?|mos?|months?)\b",
        work,
    )
    if dur:
        n = float(dur.group(1))
        unit = dur.group(2)
        if unit.startswith(("wk", "week")):
            duration_days = int(round(n * 7))
        elif unit.startswith("mo"):
            duration_days = int(round(n * 30))  # documented approximation
        else:
            duration_days = int(round(n))
        work = _blank(work, dur.span())

    # -- route phrases -----------------------------------------------------
    for pat, r in _PHRASE_ROUTES:
        m = pat.search(work)
        if m:
            if route is None:
                route = r
            work = _blank(work, m.span())

    # -- timing phrases (consumed, unmodeled) ------------------------------
    for pat in _TIMING_PHRASES:
        work = pat.sub(" ", work)

    # -- frequency phrases ---------------------------------------------------
    def _set_freq(value: tuple[int, float, PeriodUnit]) -> None:
        nonlocal freq
        if freq is None:
            freq = value

    phrase_freqs: list[tuple[re.Pattern[str], object]] = [
        (re.compile(r"\bevery other day\b"), (1, 2.0, "d")),
        (re.compile(r"\bonce (?:a|per) day\b"), (1, 1.0, "d")),
        (re.compile(r"\bonce daily\b"), (1, 1.0, "d")),
        (re.compile(r"\btwice (?:a|per) day\b"), (2, 1.0, "d")),
        (re.compile(r"\btwice daily\b"), (2, 1.0, "d")),
        (re.compile(r"\bthree times (?:a|per) day\b"), (3, 1.0, "d")),
        (re.compile(r"\btwo times daily\b"), (2, 1.0, "d")),
        (re.compile(r"\bthree times daily\b"), (3, 1.0, "d")),
        (re.compile(r"\bfour times daily\b"), (4, 1.0, "d")),
        (re.compile(r"\bfour times (?:a|per) day\b"), (4, 1.0, "d")),
        (re.compile(r"\bat bedtime\b"), (1, 1.0, "d")),
        (re.compile(r"\bat night\b"), (1, 1.0, "d")),
        (re.compile(r"\bnightly\b"), (1, 1.0, "d")),
        (re.compile(r"\bevery morning\b"), (1, 1.0, "d")),
        (re.compile(r"\bevery evening\b"), (1, 1.0, "d")),
        (re.compile(r"\bonce (?:a|per) week\b"), (1, 1.0, "wk")),
        (re.compile(r"\btwice (?:a|per) week\b"), (2, 1.0, "wk")),
        (re.compile(r"\bevery week\b"), (1, 1.0, "wk")),
        (re.compile(r"\bweekly\b"), (1, 1.0, "wk")),
    ]
    for pat, value in phrase_freqs:
        m = pat.search(work)
        if m:
            _set_freq(value)  # type: ignore[arg-type]
            work = _blank(work, m.span())

    m = re.search(r"\bevery (\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?) hours?\b", work)
    if m:
        _set_freq((1, float(m.group(2)), "h"))
        range_notes.append(m.group(0))
        work = _blank(work, m.span())
    m = re.search(r"\bevery (\d+(?:\.\d+)?) hours?\b", work)
    if m:
        _set_freq((1, float(m.group(1)), "h"))
        work = _blank(work, m.span())
    m = re.search(
        r"\b(one|two|three|four|five|six|\d+) times (?:a|per) day\b", work)
    if m:
        n = _NUMBER_WORDS.get(m.group(1))
        _set_freq((int(n if n is not None else float(m.group(1))), 1.0, "d"))
        work = _blank(work, m.span())

    # -- tokens --------------------------------------------------------------
    raw_tokens = work.split()
    tokens = [t.strip(".,;:()") for t in raw_tokens]
    consumed = [False] * len(tokens)

    prn_index: int | None = None
    for i, tok in enumerate(tokens):
        if tok in ("prn", "p.r.n."):
            prn_index = i
            consumed[i] = True

    # "as needed" with no prn token
    as_needed = prn_index is not None
    if not as_needed:
        for i in range(len(tokens) - 1):
            if tokens[i] == "as" and tokens[i + 1] == "needed":
                prn_index = i
                consumed[i] = consumed[i + 1] = True
                as_needed = True
                break

    dose_value: float | None = None
    dose_unit: str | None = None

    for i, tok in enumerate(tokens):
        if consumed[i]:
            continue
        if tok in _AS_DIRECTED_TOKENS:
            as_directed = True
            consumed[i] = True
            continue
        if tok in _TOKEN_ROUTES and route is None:
            route = _TOKEN_ROUTES[tok]
            consumed[i] = True
            continue
        if tok in _TOKEN_ROUTES:
            consumed[i] = True  # duplicate route token; still understood
            continue
        if tok in _TOKEN_FREQS:
            _set_freq(_TOKEN_FREQS[tok])
            consumed[i] = True
            continue
        if tok in _TIMING_TOKENS:
            consumed[i] = True
            continue
        # qNh / qN-Mh interval tokens
        qm = re.fullmatch(r"q(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?h?", tok)
        if qm and tok.startswith("q") and tok not in _TOKEN_FREQS:
            if qm.group(2) is not None:
                _set_freq((1, float(qm.group(2)), "h"))
                range_notes.append(tok)
            else:
                _set_freq((1, float(qm.group(1)), "h"))
            consumed[i] = True
            continue

    # -- dose: number (or range) immediately followed by a dose unit --------
    for i, tok in enumerate(tokens):
        if consumed[i]:
            continue
        # attached strength token, e.g. "500mg", "10ml", "50mcg"
        am = re.fullmatch(r"(\d+(?:\.\d+)?)(mg|mcg|µg|ug|ml|cc|iu)", tok)
        if am and dose_value is None:
            dose_value = float(am.group(1))
            dose_unit = _DOSE_UNITS[am.group(2)][0]
            consumed[i] = True
            continue
        # range token, e.g. "1-2" (unit follows) — lower bound, noted
        rm = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", tok)
        if rm and dose_value is None and i + 1 < len(tokens) \
                and tokens[i + 1] in _DOSE_UNITS:
            dose_value = float(rm.group(1))
            dose_unit = _DOSE_UNITS[tokens[i + 1]][0]
            range_notes.append(tok)
            consumed[i] = consumed[i + 1] = True
            continue
        value = _number(tok)
        if value is None or dose_value is not None:
            continue
        # "1 1/2 tabs": integer token followed by fraction token + unit
        if i + 2 < len(tokens) and tokens[i + 2] in _DOSE_UNITS:
            frac = _number(tokens[i + 1])
            if frac is not None and 0 < frac < 1 and float(tok).is_integer() \
                    and tok not in _NUMBER_WORDS:
                unit, mult = _DOSE_UNITS[tokens[i + 2]]
                dose_value = (value + frac) * mult if unit == "mL" \
                    else value + frac
                dose_unit = unit
                consumed[i] = consumed[i + 1] = consumed[i + 2] = True
                continue
        if i + 1 < len(tokens) and tokens[i + 1] in _DOSE_UNITS:
            unit, mult = _DOSE_UNITS[tokens[i + 1]]
            dose_value = value * mult
            dose_unit = unit
            consumed[i] = consumed[i + 1] = True
            continue

    # -- leftovers: reason (after prn) vs unparsed (material) ---------------
    reason_tokens: list[str] = []
    leftover: list[str] = []
    for i, tok in enumerate(tokens):
        if consumed[i] or not tok:
            continue
        if tok in _FILLER_TOKENS or tok in _TIMING_TOKENS:
            continue
        if prn_index is not None and i > prn_index:
            reason_tokens.append(tok)
        else:
            leftover.append(tok)

    as_needed_reason = " ".join(reason_tokens) if reason_tokens else None
    unparsed_parts = leftover + range_notes
    unparsed = " ".join(unparsed_parts)

    # -- confidence ------------------------------------------------------------
    if freq is not None:
        frequency_count, frequency_period, frequency_period_unit = freq
    else:
        frequency_count = frequency_period = frequency_period_unit = None

    confidence = 1.0
    if as_directed:
        confidence = min(confidence, 0.3)
    if unparsed:
        confidence = min(confidence, 0.4)
    if dose_value is None and freq is None and not as_directed:
        confidence = min(confidence, 0.1)
    else:
        if dose_value is None and not as_directed:
            confidence -= 0.2
        if freq is None and not as_directed:
            confidence -= 0.2
    confidence = round(max(0.0, min(1.0, confidence)), 2)

    return SigResult(
        dose_value=dose_value,
        dose_unit=dose_unit,
        route=route,
        frequency_count=frequency_count,
        frequency_period=frequency_period,
        frequency_period_unit=frequency_period_unit,
        as_needed=as_needed,
        as_needed_reason=as_needed_reason,
        duration_days=duration_days,
        confidence=confidence,
        unparsed=unparsed,
    )
