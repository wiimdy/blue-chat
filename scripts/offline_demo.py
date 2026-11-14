"""Runs entirely offline; no Bluetooth or chat server connection is made."""

from pathlib import Path
from tempfile import TemporaryDirectory

from matterbridge_bt_relay.outbox import Outbox
from matterbridge_bt_relay.protocol import Message, decode_frame, encode_frame

if __name__ == "__main__":
    message = Message.new(origin="internal", channel="general", sender="alice", text="안녕하세요!")
    with TemporaryDirectory() as temp:
        with Outbox(Path(temp) / "outbox.db") as outbox:
            outbox.enqueue(message)
            print("Pending:", len(outbox.pending()))
            received = decode_frame(encode_frame(outbox.pending()[0]))
            print("Received:", received.text)
            outbox.ack(received.id)
            print("Pending after ACK:", len(outbox.pending()))
