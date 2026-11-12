import asyncio
import struct
import unittest

from matterbridge_bt_relay.protocol import Message, MAX_PAYLOAD_BYTES, decode_frame, encode_frame, read_frame


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
