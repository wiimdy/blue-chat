"""Persist a message before connecting, deliver after reconnection."""

import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from matterbridge_bt_relay.outbox import Outbox
from matterbridge_bt_relay.protocol import Message
from matterbridge_bt_relay.relay import RelaySession
from matterbridge_bt_relay.transport import PacketSocket


class IdleAPI:
    def __init__(self):
        self.received = []

    def get_messages(self):
        return []

    def post_message(self, *, origin, sender, text):
        self.received.append((origin, sender, text))


class ReconnectTests(unittest.TestCase):
    def test_pending_message_survives_reopening_store_and_gets_acked(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "a.db"
            msg = Message.new(
                origin="inside", channel="general", sender="alice", text="저장 후 전송"
            )
            with Outbox(db) as store:
                store.enqueue(msg)
            left, right = socket.socketpair()
            try:
                with Outbox(db) as a_store, Outbox(Path(d) / "b.db") as b_store:
                    a_api, b_api = IdleAPI(), IdleAPI()
                    a = RelaySession(
                        api=a_api,
                        store=a_store,
                        transport=PacketSocket(left),
                        origin="inside",
                        channel="general",
                        poll_interval=0.02,
                        retry_interval=0.05,
                    )
                    b = RelaySession(
                        api=b_api,
                        store=b_store,
                        transport=PacketSocket(right),
                        origin="outside",
                        channel="general",
                        poll_interval=0.02,
                        retry_interval=0.05,
                    )
                    threads = [
                        threading.Thread(target=x.run, daemon=True) for x in (a, b)
                    ]
                    for t in threads:
                        t.start()
                    try:
                        deadline = time.monotonic() + 4
                        while (
                            a_store.pending() or not b_api.received
                        ) and time.monotonic() < deadline:
                            time.sleep(0.02)
                        self.assertEqual(
                            b_api.received, [("inside", "alice", "저장 후 전송")]
                        )
                        self.assertEqual(a_store.pending(), [])
                    finally:
                        for x in (a, b):
                            x.stop.set()
                            x.transport.close()
                        for t in threads:
                            t.join(timeout=2)
            finally:
                left.close()
                right.close()
            with Outbox(db) as store:
                self.assertEqual(store.pending(), [])
