"""End-to-end two-relay smoke test over real local sockets and fake HTTP APIs."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from matterbridge_bt_relay.outbox import Outbox
from matterbridge_bt_relay.relay import RelaySession
from matterbridge_bt_relay.transport import PacketSocket


class FakeAPI:
    def __init__(self):
        self.queue = []
        self.posts = []
        self.lock = threading.Lock()

    def push(self, sender, text):
        with self.lock:
            self.queue.append({"protocol": "mattermost", "username": sender,
                               "text": text, "event": ""})

    def get_messages(self):
        with self.lock:
            events, self.queue = self.queue, []
            return events

    def post_message(self, *, origin, sender, text):
        with self.lock:
            self.posts.append((origin, sender, text))
            # A message returned from the chat service must not bounce forever.
            self.queue.append({"protocol": "mattermost",
                               "username": f"[blue-chat/{origin}] {sender}",
                               "text": text})


def until(condition, timeout=4.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for relay")


class IntegrationTests(unittest.TestCase):
    def test_bidirectional_delivery_ack_dedup_and_loop_suppression(self):
        with tempfile.TemporaryDirectory() as path:
            a_sock, b_sock = socket.socketpair()
            a_api, b_api = FakeAPI(), FakeAPI()
            with Outbox(Path(path) / "a.db") as a_store, Outbox(Path(path) / "b.db") as b_store:
                a = RelaySession(api=a_api, store=a_store, transport=PacketSocket(a_sock),
                                 origin="inside", channel="general", poll_interval=0.02,
                                 retry_interval=0.08)
                b = RelaySession(api=b_api, store=b_store, transport=PacketSocket(b_sock),
                                 origin="outside", channel="general", poll_interval=0.02,
                                 retry_interval=0.08)
                threads = [threading.Thread(target=x.run, daemon=True) for x in [a, b]]
                for t in threads: t.start()
                try:
                    a_api.push("alice", "안녕하세요 👋")
                    until(lambda: len(b_api.posts) == 1)
                    self.assertEqual(b_api.posts[0], ("inside", "alice", "안녕하세요 👋"))
                    until(lambda: len(a_store.pending()) == 0)
                    b_api.push("bob", "반갑습니다!")
                    until(lambda: len(a_api.posts) == 1)
                    self.assertEqual(a_api.posts[0], ("outside", "bob", "반갑습니다!"))
                    until(lambda: len(b_store.pending()) == 0)
                    time.sleep(0.25)
                    self.assertEqual(len(a_api.posts), 1)
                    self.assertEqual(len(b_api.posts), 1)
                finally:
                    for x in [a, b]: x.stop.set()
                    for x in [a, b]: x.transport.close()
                    for t in threads: t.join(timeout=2)
                    self.assertFalse(any(t.is_alive() for t in threads))
