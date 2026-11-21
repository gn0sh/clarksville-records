"""One JSON parse for outside and on-disk JSON (docs/architecture/daylight-national.md 4.4.3,
`collector-input/json-depth-recursion`, security S2a finding 2).

`parse_json(raw)` -> the value, or None when it cannot be read: any `Exception` from the decode or `json.loads`
(RecursionError and MemoryError included) is "unreadable", never raised; so is a value nested deeper than MAX_DEPTH
levels (checked without recursion), so a later recursive walk of the value (`copy.deepcopy`, `bind_feed`,
`clean_feed`, schema validation) never meets nesting it cannot handle. JSON `null` also gives None: no caller here
accepts a top-level null, so it is unreadable at every site too.
"""
from __future__ import annotations

import json

MAX_DEPTH = 32       # levels of arrays/objects; our deepest real document (a feed, a cache file) is about 6


def depth_ok(value, max_depth: int = MAX_DEPTH) -> bool:
    """True when `value` (as json.loads returns it) nests no deeper than `max_depth` arrays/objects. Iterative."""
    stack = [(value, 0)]
    while stack:
        v, d = stack.pop()
        if isinstance(v, (dict, list)):
            if d + 1 > max_depth:
                return False
            stack.extend((x, d + 1) for x in (v.values() if isinstance(v, dict) else v))
    return True


def parse_json(raw, encoding: str = "utf-8", max_depth: int = MAX_DEPTH):
    """`raw` (bytes, decoded with `encoding`, or str) -> the parsed value, or None when it is unreadable: any exception
    while decoding or parsing, or nesting deeper than `max_depth`. Never raises an `Exception`."""
    try:
        text = bytes(raw).decode(encoding) if isinstance(raw, (bytes, bytearray, memoryview)) else raw
        value = json.loads(text)
        return value if depth_ok(value, max_depth) else None
    except Exception:            # RecursionError, MemoryError, UnicodeDecodeError, ValueError, TypeError, ...
        return None
