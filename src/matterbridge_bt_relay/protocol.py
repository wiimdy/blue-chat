"""Transport-agnostic message protocol for an explicitly authorized relay."""

from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

MAX_PAYLOAD_BYTES = 64 * 1024


@dataclass(frozen=True)
class Message:
    id: str
    origin: str
    channel: str
    sender: str
    text: str
    timestamp: str

    @classmethod
    def new(cls, *, origin: str, channel: str, sender: str, text: str) -> "Message":
        message = cls(
            id=str(uuid4()),
            origin=origin,
            channel=channel,
            sender=sender,
            text=text,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return cls.from_dict(asdict(message))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        fields = ("id", "origin", "channel", "sender", "text", "timestamp")
        if set(data) != set(fields):
            raise ValueError("unexpected or missing message fields")
        if any(not isinstance(data[name], str) for name in fields):
            raise ValueError("message fields must be strings")
        try:
            for name in fields:
                data[name].encode("utf-8")
            UUID(data["id"])
            parsed = datetime.fromisoformat(data["timestamp"])
            if parsed.tzinfo is None:
                raise ValueError("timestamp must contain timezone")
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid message UTF-8, ID or timestamp") from exc
        if not data["origin"] or not data["channel"] or not data["sender"]:
            raise ValueError("origin, channel and sender must be non-empty")
        return cls(**data)


def encode_frame(message: Message) -> bytes:
    """Length-prefix a UTF-8 JSON message with a big-endian 32-bit size."""
    body = asdict(message)
    Message.from_dict(body)
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not 0 < len(payload) <= MAX_PAYLOAD_BYTES:
        raise ValueError("payload too large or empty")
    return struct.pack("!I", len(payload)) + payload


def decode_frame(frame: bytes) -> Message:
    if len(frame) < 4:
        raise ValueError("truncated frame header")
    (size,) = struct.unpack("!I", frame[:4])
    if not 0 < size <= MAX_PAYLOAD_BYTES or len(frame) != size + 4:
        raise ValueError("invalid frame length")
    try:
        body = json.loads(frame[4:].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid UTF-8 JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("frame body must be an object")
    return Message.from_dict(body)


async def read_frame(reader: asyncio.StreamReader) -> Message:
    """Read precisely one framed message from a stream-like transport."""
    header = await reader.readexactly(4)
    (size,) = struct.unpack("!I", header)
    if not 0 < size <= MAX_PAYLOAD_BYTES:
        raise ValueError("invalid frame length")
    payload = await reader.readexactly(size)
    return decode_frame(header + payload)
