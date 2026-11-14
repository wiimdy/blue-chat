"""Regression tests for destructive polling and receiver shutdown."""

import socket
import threading
import unittest

from matterbridge_bt_relay.outbox import Outbox
from matterbridge_bt_relay.protocol import Message
from matterbridge_bt_relay.relay import RelaySession
from matterbridge_bt_relay.transport import Ack, PacketSocket


class RecordingAPI:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.posts: list[tuple[str, str, str]] = []
        self.fail_next_post = False

    def get_messages(self) -> list[dict]:
        events, self.events = self.events, []
        return events

    def post_message(self, *, origin: str, sender: str, text: str) -> None:
        if self.fail_next_post:
            self.fail_next_post = False
            raise OSError("temporary API failure")
        self.posts.append((origin, sender, text))


class RelayReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Outbox(":memory:")
        local, peer = socket.socketpair()
        self.transport = PacketSocket(local)
        self.peer = PacketSocket(peer)
        self.api = RecordingAPI()
        self.session = RelaySession(
            api=self.api,
            store=self.store,
            transport=self.transport,
            origin="local",
            channel="general",
            poll_interval=0.01,
        )

    def tearDown(self) -> None:
        self.session.stop.set()
        self.transport.close()
        self.peer.close()
        self.store.close()

    def test_invalid_routing_metadata_is_rejected_before_polling(self) -> None:
        for origin in ("\ud800", "x" * 65536):
            with self.subTest(origin_length=len(origin)), self.assertRaises(ValueError):
                RelaySession(
                    api=self.api,
                    store=self.store,
                    transport=self.transport,
                    origin=origin,
                    channel="general",
                )

    def test_unhashable_userid_does_not_discard_poll_batch(self) -> None:
        self.api.events = [
            {"username": "alice", "text": "first", "userid": []},
            {"username": "bob", "text": "second"},
        ]
        self.session._poll()
        self.assertEqual([msg.text for msg in self.store.pending()], ["first", "second"])

    def test_invalid_unicode_does_not_discard_later_valid_events(self) -> None:
        self.api.events = [
            {"username": "alice", "text": "\ud800"},
            {"username": "\ud800", "text": "invalid sender"},
            {"username": "bob", "text": "valid"},
        ]
        self.session._poll()
        self.assertEqual([msg.text for msg in self.store.pending()], ["valid"])

    def test_failed_post_can_retry_and_duplicate_is_acked_without_reposting(self) -> None:
        message = Message.new(origin="remote", channel="general", sender="alice", text="hello")
        self.api.fail_next_post = True
        receiver = threading.Thread(target=self.session._receive)
        receiver.start()
        try:
            self.peer.send(message)
            self.peer.send(message)
            self.assertEqual(self.peer.receive(), Ack(message.id))
            self.peer.send(message)
            self.assertEqual(self.peer.receive(), Ack(message.id))
            self.assertEqual(self.api.posts, [("remote", "alice", "hello")])
        finally:
            self.session.stop.set()
            self.transport.close()
            receiver.join(timeout=2)
            self.assertFalse(receiver.is_alive())

    def test_run_waits_for_slow_post_before_returning(self) -> None:
        posting = threading.Event()
        release_post = threading.Event()
        finished = threading.Event()

        class SlowAPI(RecordingAPI):
            def post_message(self, *, origin: str, sender: str, text: str) -> None:
                posting.set()
                release_post.wait(timeout=10)
                super().post_message(origin=origin, sender=sender, text=text)

        slow_api = SlowAPI()
        self.session.api = slow_api

        def run() -> None:
            try:
                self.session.run()
            finally:
                finished.set()

        runner = threading.Thread(target=run)
        runner.start()
        try:
            self.peer.send(Message.new(
                origin="remote", channel="general", sender="alice", text="slow post"
            ))
            self.assertTrue(posting.wait(timeout=2))
            self.session.stop.set()
            self.assertFalse(finished.wait(timeout=3.2))
            release_post.set()
            self.assertTrue(finished.wait(timeout=2))
            self.assertEqual(slow_api.posts, [("remote", "alice", "slow post")])
        finally:
            release_post.set()
            self.session.stop.set()
            self.transport.close()
            runner.join(timeout=2)
            self.assertFalse(runner.is_alive())
