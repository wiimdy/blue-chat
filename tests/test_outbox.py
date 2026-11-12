import tempfile
from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
