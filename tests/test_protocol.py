import asyncio
import json
import struct
import unittest
from dataclasses import asdict, replace

from matterbridge_bt_relay.protocol import (
    MAX_PAYLOAD_BYTES,
    Message,
    decode_frame,
    encode_frame,
    read_frame,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.message = Message.new(origin="internal", channel="general", sender="alice", text="한글 테스트")

    def test_roundtrip(self):
        self.assertEqual(self.message, decode_frame(encode_frame(self.message)))

    def test_reject_truncated(self):
        with self.assertRaises(ValueError):
            decode_frame(b"\0\0")

    def test_reject_oversize(self):
        with self.assertRaises(ValueError):
            decode_frame(struct.pack("!I", MAX_PAYLOAD_BYTES + 1))

    def test_reject_bad_data(self):
        with self.assertRaises(ValueError):
            decode_frame(struct.pack("!I", 3) + b"bad")

    def test_encoder_rejects_invalid_messages(self) -> None:
        for field, value in (("origin", ""), ("channel", ""), ("sender", ""),
                             ("id", "invalid"), ("timestamp", "2026-01-01"),
                             ("text", 42)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                encode_frame(replace(self.message, **{field: value}))

    def test_new_rejects_invalid_fields(self) -> None:
        with self.assertRaises(ValueError):
            Message.new(origin="", channel="general", sender="alice", text="hello")

    def test_decoder_rejects_unpaired_unicode_surrogates(self) -> None:
        for field in ("origin", "channel", "sender", "text"):
            body = asdict(self.message)
            body[field] = "\ud800"
            payload = json.dumps(body).encode("utf-8")
            with self.subTest(field=field), self.assertRaises(ValueError):
                decode_frame(struct.pack("!I", len(payload)) + payload)

    def test_decoder_reports_deep_json_as_invalid(self) -> None:
        payload = b"[" * 2000 + b"0" + b"]" * 2000
        with self.assertRaises(ValueError):
            decode_frame(struct.pack("!I", len(payload)) + payload)

    def test_stream_partial_reads(self):
        async def run():
            r = asyncio.StreamReader()
            frame = encode_frame(self.message)
            r.feed_data(frame[:2])
            r.feed_data(frame[2:7])
            r.feed_data(frame[7:])
            r.feed_eof()
            return await read_frame(r)
        self.assertEqual(self.message, asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
