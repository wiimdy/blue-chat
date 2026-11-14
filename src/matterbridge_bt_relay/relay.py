"""Bidirectional text-only relay, one source API per device.

Transport independent: PacketSocket may wrap Linux RFCOMM or localhost TCP
(for integration tests). No IP forwarding or arbitrary RPC.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

from .outbox import Outbox
from .protocol import Message, encode_frame
from .transport import Ack, PacketSocket

logger = logging.getLogger(__name__)

MAX_TEXT_BYTES = 8000


class ChatAPI(Protocol):
    def get_messages(self) -> list[dict]: ...
    def post_message(self, *, origin: str, sender: str, text: str) -> None: ...


class RelaySession:
    def __init__(self, *, api: ChatAPI, store: Outbox, transport: PacketSocket,
                 origin: str, channel: str, poll_interval: float = 0.25,
                 retry_interval: float = 2.0, gateway: str | None = None,
                 ignored_senders: frozenset[str] = frozenset(),
                 ignored_userids: frozenset[str] = frozenset()) -> None:
        if not origin or not channel:
            raise ValueError("origin and logical channel required")
        # Reject unusable routing metadata before consuming destructive API reads.
        encode_frame(Message.new(origin=origin, channel=channel, sender="relay", text=""))
        self.api = api
        self.store = store
        self.transport = transport
        self.origin = origin
        self.channel = channel
        self.poll_interval = poll_interval
        self.retry_interval = retry_interval
        self.gateway = gateway
        self.ignored_senders = ignored_senders
        self.ignored_userids = ignored_userids
        self.stop = threading.Event()
        self._reader_error: BaseException | None = None

    def _poll(self) -> None:
        for event in self.api.get_messages():
            text = event.get("text")
            sender = event.get("username")
            if (not isinstance(text, str) or not text.strip() or
                    not isinstance(sender, str) or not sender.strip()):
                continue
            userid = event.get("userid")
            if (event.get("protocol") == "api" or "[blue-chat/" in sender or
                    sender in self.ignored_senders or
                    (isinstance(userid, str) and userid in self.ignored_userids)):
                continue
            if event.get("event"):
                continue
            if self.gateway and event.get("gateway") != self.gateway:
                continue
            try:
                if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
                    logger.warning("skipping oversized incoming message")
                    continue
                msg = Message.new(origin=self.origin, channel=self.channel,
                                  sender=sender[:128], text=text)
                self.store.enqueue(msg)
            except ValueError as exc:
                # This API batch is already consumed; preserve later valid events.
                logger.warning("skipping invalid incoming message: %s", type(exc).__name__)

    def _receive(self) -> None:
        try:
            while not self.stop.is_set():
                packet = self.transport.receive(self.stop)
                if isinstance(packet, Ack):
                    self.store.ack(packet.id)
                elif isinstance(packet, Message):
                    if packet.origin == self.origin or packet.channel != self.channel:
                        logger.warning("rejecting unexpected message source/channel")
                        continue
                    if len(packet.text.encode("utf-8")) > MAX_TEXT_BYTES:
                        continue
                    if self.store.register_incoming(packet.id):
                        self.transport.send(Ack(packet.id))
                        continue
                    try:
                        self.api.post_message(origin=packet.origin,
                                              sender=packet.sender, text=packet.text)
                    except Exception as exc:
                        # No ACK; sender will retry. This is at-least-once delivery.
                        logger.warning("Matterbridge POST failed: %s", type(exc).__name__)
                        continue
                    self.store.mark_posted(packet.id)
                    self.transport.send(Ack(packet.id))
        except (EOFError, OSError, ValueError) as exc:
            if not self.stop.is_set():
                self._reader_error = exc
                logger.info("peer disconnected: %s", type(exc).__name__)
        finally:
            self.stop.set()

    def run(self) -> None:
        reader = threading.Thread(target=self._receive, daemon=True)
        reader.start()
        last_sent: dict[str, float] = {}
        try:
            while not self.stop.is_set():
                try:
                    self._poll()
                except Exception as exc:
                    logger.warning("Matterbridge polling failed: %s", type(exc).__name__)
                now = time.monotonic()
                for msg in self.store.pending():
                    if self.stop.is_set():
                        break
                    if now - last_sent.get(msg.id, -float("inf")) >= self.retry_interval:
                        try:
                            self.transport.send(msg)
                        except OSError:
                            self.stop.set()
                            break
                        last_sent[msg.id] = now
                self.stop.wait(self.poll_interval)
        finally:
            self.stop.set()
            self.transport.close()
            # A pending API POST must finish before reconnect or store shutdown.
            reader.join()
