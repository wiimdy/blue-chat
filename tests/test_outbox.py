import tempfile
import unittest
from pathlib import Path

from matterbridge_bt_relay.outbox import Outbox
from matterbridge_bt_relay.protocol import Message


class OutboxTests(unittest.TestCase):
    def test_enqueue_duplicate_ack_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.db"
            msg = Message.new(origin="internal", channel="general", sender="alice", text="hi")
            with Outbox(path) as box:
                box.enqueue(msg)
                box.enqueue(msg)
                self.assertEqual([msg], box.pending())
            with Outbox(path) as box:
                self.assertEqual([msg], box.pending())
                box.ack(msg.id)
                self.assertEqual([], box.pending())

    def test_incoming_posted_state_survives_reopening_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.db"
            msg = Message.new(origin="remote", channel="general", sender="alice", text="hi")
            with Outbox(path) as box:
                self.assertFalse(box.register_incoming(msg.id))
            with Outbox(path) as box:
                # Receiving alone must not suppress a failed or interrupted POST.
                self.assertFalse(box.register_incoming(msg.id))
                box.mark_posted(msg.id)
            with Outbox(path) as box:
                self.assertTrue(box.register_incoming(msg.id))


if __name__ == "__main__":
    unittest.main()
