"""HL7 v2 message parser for legacy feed files (all data synthetic).

Small, dependency-free, and deliberately tolerant: Halcyon feeds are messy
(v2.3, latin-1 names, trailing separators, Z-segments), so parsing never
raises on message content. The only exception is a malformed accessor path,
which is a programmer error and raises ``ValueError``.

Accessor conventions (also documented on :class:`Message`):

- Paths look like ``"PID-5"``, ``"PID-5.1"``, ``"PID-5.1.2"`` (field,
  component, subcomponent; all 1-based, as in HL7).
- ``seg_index`` is 0-based: ``seg_index=0`` is the first occurrence of the
  segment in the message (the default), ``seg_index=2`` the third.
- A missing segment, field, component, or subcomponent returns ``None``
  from ``get`` and ``[]`` from ``get_all``. A field that is present but
  empty returns ``""``, so callers can tell "absent" from "blank".
- ``get`` returns the first repetition of a field; ``get_all`` returns
  every repetition, positionally aligned with the raw field.
- Returned values are unescaped (``\\F\\`` -> the field separator, and so
  on). Unknown escape sequences are passed through unchanged.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import re

__all__ = ["Encoding", "Message", "Segment", "iter_messages", "parse_message"]


@dataclass(frozen=True)
class Encoding:
    """Delimiter and escape characters declared by MSH-1 / MSH-2."""

    field_separator: str = "|"
    component_separator: str = "^"
    repetition_separator: str = "~"
    escape_character: str = "\\"
    subcomponent_separator: str = "&"


@lru_cache(maxsize=16)
def _escape_pattern(escape_character: str) -> re.Pattern[str]:
    esc = re.escape(escape_character)
    return re.compile(rf"{esc}(F|S|T|R|E|\.br){esc}", re.IGNORECASE)


def _unescape(value: str, encoding: Encoding) -> str:
    """Resolve HL7 escape sequences in a leaf value.

    ``\\F\\ \\S\\ \\T\\ \\R\\ \\E\\`` become the message's own delimiter
    characters (so with a ``*`` field separator, ``\\F\\`` unescapes to
    ``*``, not ``|``). ``\\.br\\`` becomes a newline. Unknown sequences are
    left exactly as written.
    """
    escape = encoding.escape_character
    if escape not in value:
        return value
    replacements = {
        "F": encoding.field_separator,
        "S": encoding.component_separator,
        "T": encoding.subcomponent_separator,
        "R": encoding.repetition_separator,
        "E": escape,
        ".BR": "\n",
    }

    def replace(match: re.Match[str]) -> str:
        return replacements[match[1].upper()]

    return _escape_pattern(escape).sub(replace, value)


def _decode(data: bytes) -> str:
    """Decode feed bytes: UTF-8 (BOM tolerated) first, latin-1 fallback."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


@dataclass(frozen=True)
class Segment:
    """One HL7 segment. ``fields[n - 1]`` is HL7 field ``n`` (raw text).

    For MSH, field 1 is the field separator character itself and field 2
    is the MSH-2 encoding string, matching standard HL7 numbering.
    """

    name: str
    fields: tuple[str, ...] = ()
    encoding: Encoding = field(default_factory=Encoding)

    def _raw_field(self, field_number: int) -> str | None:
        if 1 <= field_number <= len(self.fields):
            return self.fields[field_number - 1]
        return None

    def _is_encoding_field(
        self,
        field_number: int,
        component: int | None,
        subcomponent: int | None,
    ) -> bool:
        return (
            self.name == "MSH"
            and field_number == 2
            and component is None
            and subcomponent is None
        )

    def get(
        self,
        field_number: int,
        component: int | None = None,
        subcomponent: int | None = None,
        *,
        repetition: int = 0,
    ) -> str | None:
        """Return one value, unescaped; ``None`` when absent.

        ``component``/``subcomponent`` are 1-based. Without a component,
        returns the whole field (one repetition) with repetitions and
        delimiters resolved by the caller via ``repetition``.
        """
        if subcomponent is not None and component is None:
            raise ValueError("subcomponent requires a component")
        raw = self._raw_field(field_number)
        if raw is None:
            return None
        if self._is_encoding_field(field_number, component, subcomponent):
            # MSH-2's content *is* the delimiter set; never split it.
            return raw
        reps = raw.split(self.encoding.repetition_separator)
        if not 0 <= repetition < len(reps):
            return None
        value = reps[repetition]
        if component is None:
            return _unescape(value, self.encoding)
        parts = value.split(self.encoding.component_separator)
        if not 1 <= component <= len(parts):
            return None
        value = parts[component - 1]
        if subcomponent is None:
            return _unescape(value, self.encoding)
        subs = value.split(self.encoding.subcomponent_separator)
        if not 1 <= subcomponent <= len(subs):
            return None
        return _unescape(subs[subcomponent - 1], self.encoding)

    def get_all(
        self,
        field_number: int,
        component: int | None = None,
        subcomponent: int | None = None,
    ) -> list[str]:
        """Return the value across every repetition of the field.

        The list is positionally aligned with the field's repetitions;
        a repetition lacking the requested component contributes ``""``.
        Absent field -> ``[]``.
        """
        raw = self._raw_field(field_number)
        if raw is None:
            return []
        if self._is_encoding_field(field_number, component, subcomponent):
            return [raw]
        count = len(raw.split(self.encoding.repetition_separator))
        values = []
        for i in range(count):
            value = self.get(field_number, component, subcomponent, repetition=i)
            values.append(value if value is not None else "")
        return values


_PATH = re.compile(r"^([A-Za-z][A-Za-z0-9]{2})-(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def _parse_path(path: str) -> tuple[str, int, int | None, int | None]:
    match = _PATH.match(path)
    if match is None:
        raise ValueError(
            f"Invalid field path {path!r}; expected e.g. 'PID-5' or 'PID-5.1'"
        )
    name, field_number, component, subcomponent = match.groups()
    return (
        name.upper(),
        int(field_number),
        int(component) if component is not None else None,
        int(subcomponent) if subcomponent is not None else None,
    )


@dataclass
class Message:
    """A parsed HL7 v2 message: ordered segments plus its encoding."""

    segments: list[Segment] = field(default_factory=list)
    encoding: Encoding = field(default_factory=Encoding)

    @property
    def type(self) -> str | None:
        """Message type from MSH-9, e.g. ``"ADT^A08"``; ``None`` if absent."""
        msh = self.segment("MSH")
        value = msh.get(9) if msh is not None else None
        return value if value else None

    @property
    def control_id(self) -> str | None:
        """Message control id from MSH-10; ``None`` if absent."""
        msh = self.segment("MSH")
        value = msh.get(10) if msh is not None else None
        return value if value else None

    def segment(self, name: str, index: int = 0) -> Segment | None:
        """Return the ``index``-th (0-based) segment named ``name``."""
        seen = 0
        for seg in self.segments:
            if seg.name == name.upper():
                if seen == index:
                    return seg
                seen += 1
        return None

    def get(self, path: str, *, seg_index: int = 0) -> str | None:
        """Return the value at ``path`` (e.g. ``"PID-5.1"``), unescaped.

        ``seg_index`` selects among repeated segments (0-based), e.g.
        ``msg.get("OBX-5", seg_index=2)`` reads the third OBX. Missing
        segment/field/component -> ``None``; present-but-empty -> ``""``;
        a repeated field yields its first repetition (see ``get_all``).
        """
        name, field_number, component, subcomponent = _parse_path(path)
        seg = self.segment(name, seg_index)
        if seg is None:
            return None
        return seg.get(field_number, component, subcomponent)

    def get_all(self, path: str, *, seg_index: int = 0) -> list[str]:
        """Return ``path``'s value across all repetitions of the field.

        E.g. ``msg.get_all("PID-3")`` for a multi-identifier field, or
        ``msg.get_all("PID-3.1")`` for the first component of each
        repetition. Missing segment/field -> ``[]``.
        """
        name, field_number, component, subcomponent = _parse_path(path)
        seg = self.segment(name, seg_index)
        if seg is None:
            return []
        return seg.get_all(field_number, component, subcomponent)


_LINE_SPLIT = re.compile(r"\r\n|\r|\n")
_MSH2_DEFAULTS = "^~\\&"  # component, repetition, escape, subcomponent


def _encoding_from(first_line: str) -> Encoding:
    """Build the encoding from an MSH line; defaults when not an MSH line."""
    if not first_line.startswith("MSH"):
        return Encoding()
    field_separator = first_line[3] if len(first_line) > 3 else "|"
    parts = first_line.split(field_separator)
    declared = parts[1] if len(parts) > 1 else ""
    chars = [
        declared[i] if i < len(declared) else _MSH2_DEFAULTS[i] for i in range(4)
    ]
    return Encoding(
        field_separator=field_separator,
        component_separator=chars[0],
        repetition_separator=chars[1],
        escape_character=chars[2],
        subcomponent_separator=chars[3],
    )


def _parse_segment(line: str, encoding: Encoding) -> Segment:
    parts = line.split(encoding.field_separator)
    if parts[0] == "MSH":
        # MSH-1 is the separator itself, so it becomes field 1 and the
        # MSH-2 encoding string (parts[1]) is field 2.
        fields: tuple[str, ...] = (encoding.field_separator, *parts[1:])
    else:
        fields = tuple(parts[1:])
    return Segment(name=parts[0], fields=fields, encoding=encoding)


def parse_message(text: str | bytes) -> Message:
    """Parse one HL7 v2 message.

    Segment lines may be separated by ``\\r``, ``\\n``, or ``\\r\\n``;
    blank lines are ignored. Bytes are decoded UTF-8 first with a
    latin-1 fallback. Text without an MSH segment parses with the default
    encoding and yields ``type``/``control_id`` of ``None``. Empty text
    yields a message with no segments.
    """
    if isinstance(text, bytes):
        text = _decode(text)
    lines = [line for line in _LINE_SPLIT.split(text.lstrip("\ufeff")) if line.strip()]
    if not lines:
        return Message()
    encoding = _encoding_from(lines[0])
    segments = [_parse_segment(line, encoding) for line in lines]
    return Message(segments=segments, encoding=encoding)


def _split_message_blocks(text: str) -> Iterator[str]:
    """Split feed text into per-message blocks.

    A new message starts at a line beginning with ``MSH``; blank lines
    also close the current message. Lines before the first ``MSH`` are
    kept as their own block (parsed with default encoding).
    """
    current: list[str] = []
    for line in _LINE_SPLIT.split(text):
        if line.startswith("MSH") or not line.strip():
            if current:
                yield "\n".join(current)
                current = []
            if line.startswith("MSH"):
                current.append(line)
        else:
            current.append(line)
    if current:
        yield "\n".join(current)


def iter_messages(path: Path) -> Iterator[Message]:
    """Yield every message in a feed file, in file order.

    Files hold many messages separated by blank lines or simply by a
    line break before the next ``MSH``. Bytes are decoded UTF-8 first
    with a latin-1 fallback (Halcyon writes latin-1).
    """
    text = _decode(Path(path).read_bytes())
    for block in _split_message_blocks(text):
        message = parse_message(block)
        if message.segments:
            yield message
