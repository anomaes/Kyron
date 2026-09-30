from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any

from backend.engine.pi.json_events import PiProtocolError, parse_event
from backend.engine.pi.ui_events import normalize_pi_event, preview_pi_event

PAGE_MAX_EVENTS = 100
PAGE_MAX_SOURCE_BYTES = 1 << 20
PAGE_MAX_RESPONSE_BYTES = 512 * 1024


def _cursor(offset: int, line: int, skipping: bool, inode: int) -> str:
    raw = json.dumps([offset, line, int(skipping), inode], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None, inode: int, size: int) -> tuple[int, int, bool]:
    if cursor is None:
        return 0, 0, False
    if len(cursor) > 128:
        raise ValueError("Invalid Pi activity cursor")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if (
            not isinstance(value, list)
            or len(value) != 4
            or any(type(item) is not int for item in value)
            or value[0] < 0
            or value[1] < 0
            or value[1] > value[0]
            or value[2] not in (0, 1)
            or value[3] != inode
            or value[0] > size
        ):
            raise ValueError
        return value[0], value[1], bool(value[2])
    except (ValueError, TypeError, binascii.Error, UnicodeError) as exc:
        raise ValueError("Invalid or stale Pi activity cursor") from exc


def read_pi_event_page(
    path: Path, cursor: str | None, *, running: bool
) -> dict[str, Any]:
    """Page the original JSONL by bytes; never hold more than one bounded record."""
    with path.open("rb") as source:
        stat = os.fstat(source.fileno())
        offset, line_index, skipping = _decode_cursor(cursor, stat.st_ino, stat.st_size)
        if offset and not skipping:
            source.seek(offset - 1)
            if source.read(1) != b"\n" and offset != stat.st_size:
                raise ValueError("Pi activity cursor is not on a record boundary")
        source.seek(offset)
        read_bytes = 0
        response_bytes = 0
        incomplete = False
        events: list[dict[str, Any]] = []
        while read_bytes < PAGE_MAX_SOURCE_BYTES and len(events) < PAGE_MAX_EVENTS:
            remaining = PAGE_MAX_SOURCE_BYTES - read_bytes
            start = source.tell()
            chunk = source.readline(min(remaining, 64 * 1024) if skipping else remaining)
            if not chunk:
                break
            if skipping:
                read_bytes += len(chunk)
                if chunk.endswith(b"\n") or (not running and source.tell() == stat.st_size):
                    skipping = False
                    line_index += 1
                continue
            complete = chunk.endswith(b"\n") or (not running and source.tell() == stat.st_size)
            if not complete:
                if events or start != offset:
                    source.seek(start)
                    incomplete = True
                    break
                if len(chunk) < PAGE_MAX_SOURCE_BYTES:
                    source.seek(start)
                    incomplete = True
                    break
                read_bytes += len(chunk)
                skipping = True
                event = {
                    "event_index": line_index + 1,
                    "pi_event_type": "oversized_record",
                    "kind": "lifecycle",
                    "message": (
                        "Large Pi record: preview omitted; download raw output to inspect it."
                    ),
                }
            else:
                read_bytes += len(chunk)
                line_index += 1
                if not chunk.strip():
                    continue
                try:
                    parsed = parse_event(chunk.decode("utf-8", errors="replace"))
                except PiProtocolError:
                    event = {
                        "event_index": line_index,
                        "pi_event_type": "protocol_error",
                        "kind": "error",
                        "message": "Pi emitted malformed JSONL",
                    }
                else:
                    normalized = normalize_pi_event(parsed, line_index)
                    if normalized is None:
                        continue
                    event = preview_pi_event(normalized)
            encoded_size = len(json.dumps(event, ensure_ascii=False, default=str).encode("utf-8"))
            if response_bytes + encoded_size > PAGE_MAX_RESPONSE_BYTES:
                event = {
                    "event_index": event["event_index"],
                    "pi_event_type": "oversized_preview",
                    "kind": "lifecycle",
                    "message": "Pi record preview omitted; download raw output to inspect it.",
                }
                encoded_size = len(json.dumps(event).encode())
            events.append(event)
            response_bytes += encoded_size
        position = source.tell()
        return {
            "events": events,
            "next_cursor": _cursor(position, line_index, skipping, stat.st_ino),
            "has_more": position < stat.st_size and not incomplete,
            "source_bytes_read": read_bytes,
            "response_bytes": response_bytes,
        }
