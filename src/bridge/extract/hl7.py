"""Minimal HL7 v2 parser (v0; see TASKS.md T-101 for the hardened version's spec)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class Segment:
    name: str
    fields: list[str]  # fields[0] is the segment name; for MSH, fields[1] is the field separator


@dataclass
class Message:
    segments: list[Segment] = field(default_factory=list)
    component_sep: str = "^"
    repetition_sep: str = "~"
    escape_char: str = "\\"
    subcomponent_sep: str = "&"

    @property
    def type(self) -> str:
        return self.get("MSH-9") and "^".join(self.raw_field("MSH", 9).split(self.component_sep)[:2])

    @property
    def control_id(self) -> str:
        return self.get("MSH-10")

    def segments_named(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.name == name]

    def raw_field(self, seg: str, num: int, seg_index: int = 0) -> str:
        segs = self.segments_named(seg)
        if seg_index >= len(segs):
            return ""
        f = segs[seg_index].fields
        return f[num] if num < len(f) else ""

    def get(self, path: str, seg_index: int = 0) -> str:
        """`PID-5.1` style accessor (1-based component), first repetition, unescaped."""
        reps = self.get_all(path, seg_index)
        return reps[0] if reps else ""

    def get_all(self, path: str, seg_index: int = 0) -> list[str]:
        m = re.fullmatch(r"([A-Z0-9]{3})-(\d+)(?:\.(\d+))?(?:\.(\d+))?", path)
        if not m:
            raise ValueError(f"bad HL7 path {path!r}")
        seg, num = m.group(1), int(m.group(2))
        comp = int(m.group(3)) if m.group(3) else None
        sub = int(m.group(4)) if m.group(4) else None
        raw = self.raw_field(seg, num, seg_index)
        if seg == "MSH" and num == 2:
            return [raw]
        out = []
        for rep in raw.split(self.repetition_sep) if raw else []:
            val = rep
            if comp is not None:
                parts = rep.split(self.component_sep)
                val = parts[comp - 1] if comp - 1 < len(parts) else ""
                if sub is not None:
                    subs = val.split(self.subcomponent_sep)
                    val = subs[sub - 1] if sub - 1 < len(subs) else ""
            out.append(self.unescape(val))
        return out

    def unescape(self, s: str) -> str:
        e = self.escape_char
        if e not in s:
            return s
        table = {"F": "|", "S": self.component_sep, "R": self.repetition_sep, "T": self.subcomponent_sep,
                 "E": e, ".br": "\n"}
        return re.sub(re.escape(e) + r"(F|S|R|T|E|\.br)" + re.escape(e), lambda mm: table[mm.group(1)], s)


def parse_message(text: str) -> Message:
    lines = [ln for ln in re.split(r"\r\n|\r|\n", text.strip()) if ln.strip()]
    if not lines or not lines[0].startswith("MSH"):
        raise ValueError("message must start with MSH")
    fs = lines[0][3]
    enc = lines[0].split(fs)[1]
    msg = Message(component_sep=enc[0], repetition_sep=enc[1] if len(enc) > 1 else "~",
                  escape_char=enc[2] if len(enc) > 2 else "\\", subcomponent_sep=enc[3] if len(enc) > 3 else "&")
    for ln in lines:
        parts = ln.split(fs)
        if parts[0] == "MSH":
            parts = ["MSH", fs] + parts[1:]
        msg.segments.append(Segment(parts[0], parts))
    return msg


def iter_messages(path: Path) -> Iterator[Message]:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    for chunk in re.split(r"(?:\r\n|\r|\n)(?=MSH)", text):
        if chunk.strip():
            yield parse_message(chunk)
