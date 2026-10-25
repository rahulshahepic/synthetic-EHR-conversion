"""Fast JSON with exactly the stdlib's results.

orjson encodes about twice as fast as the json module but differs on a few inputs (NaN/Infinity become null,
unknown types are not stringified). Output goes through orjson only when it decodes back to a value equal to
the input; everything else (NaN, datetimes, tuples, non-str keys, big ints, ...) uses the json module, so
stored values never change. Text formatting may differ (no spaces after separators, raw UTF-8); every reader
parses, none compares text. Decoding stays on the json module: orjson reads integers beyond 64 bits as floats,
and guarding against that costs as much as it saves.
"""
from __future__ import annotations

import json
from typing import Any

try:
    import orjson
except ImportError:  # optional speed-up
    orjson = None

_std_encode = json.JSONEncoder(default=str).encode


def dumps(value: Any) -> str:
    """json.dumps(value, default=str), faster."""
    if orjson is not None:
        try:
            out = orjson.dumps(value, option=orjson.OPT_PASSTHROUGH_DATETIME | orjson.OPT_PASSTHROUGH_DATACLASS
                               | orjson.OPT_PASSTHROUGH_SUBCLASS)
            if orjson.loads(out) == value:
                return out.decode()
        except (TypeError, ValueError):  # orjson.JSONEncodeError / JSONDecodeError subclass these
            pass
    return _std_encode(value)

