"""Bounded framed messages and development/RFCOMM socket transports.

RFCOMM deliberately provides message transport only: no IP forwarding, proxy,
command dispatch, or file transfer. Linux RFCOMM support requires actual hardware.
"""
from __future__ import annotations

import json
import socket
import struct
import sys
import threading
from dataclasses import dataclass
from typing import Union
from uuid import UUID

from .protocol import MAX_PAYLOAD_BYTES, Message, decode_frame, encode_frame

CONNECT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Ack:
    id: str

    def __post_init__(self) -> None:
        UUID(self.id)


Packet = Union[Message, Ack]


def encode_packet(packet: Packet) -> bytes:
    if isinstance(packet, Message):
        return encode_frame(packet)
    if isinstance(packet, Ack):
        payload = json.dumps({"type": "ack", "id": packet.id}, separators=(",", ":")).encode("utf-8")
        return struct.pack("!I", len(payload)) + payload
    raise TypeError("only Message and Ack packets are supported")


def decode_packet(frame: bytes) -> Packet:
    if len(frame) < 4:
        raise ValueError("invalid packet header")
    (n,) = struct.unpack("!I", frame[:4])
    if not 0 < n <= MAX_PAYLOAD_BYTES or len(frame) != n + 4:
        raise ValueError("invalid packet length")
    try:
        doc = json.loads(frame[4:].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid JSON packet") from exc
    if not isinstance(doc, dict):
        raise ValueError("packet must be JSON object")
    if doc.get("type") == "ack":
        if set(doc) != {"type", "id"} or not isinstance(doc["id"], str):
            raise ValueError("invalid acknowledgement")
        return Ack(doc["id"])
    return decode_frame(frame)


def _read_exact(sock: socket.socket, size: int, stop: threading.Event | None = None) -> bytes:
    out = bytearray()
    while len(out) < size:
        if stop and stop.is_set():
            raise EOFError("relay stopping")
        try:
            data = sock.recv(size - len(out))
        except socket.timeout:
            continue
        if not data:
            raise EOFError("peer disconnected")
        out.extend(data)
    return bytes(out)


class PacketSocket:
    """Thread-safe full-frame writes, one reading thread per connection."""
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.sock.settimeout(0.5)
        self._send_lock = threading.Lock()

    def send(self, packet: Packet) -> None:
        with self._send_lock:
            self.sock.sendall(encode_packet(packet))

    def receive(self, stop: threading.Event | None = None) -> Packet:
        header = _read_exact(self.sock, 4, stop)
        (size,) = struct.unpack("!I", header)
        if not 0 < size <= MAX_PAYLOAD_BYTES:
            raise ValueError("invalid packet length")
        return decode_packet(header + _read_exact(self.sock, size, stop))

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


def open_socket(*, mode: str, transport: str, peer: str | None, port: int) -> socket.socket:
    """Return a connected socket. TCP test transport is limited to localhost."""
    if mode not in {"listen", "connect"}:
        raise ValueError("invalid mode")
    if transport == "tcp":
        if peer and peer not in {"127.0.0.1", "localhost"}:
            raise ValueError("TCP development transport must stay on localhost")
        family = socket.AF_INET
        proto = 0
        address = ("127.0.0.1", port)
    elif transport == "rfcomm":
        if sys.platform != "linux" or not hasattr(socket, "AF_BLUETOOTH"):
            raise RuntimeError("standard-library RFCOMM transport currently supports Linux only")
        family = socket.AF_BLUETOOTH
        proto = socket.BTPROTO_RFCOMM
        if mode == "connect" and not peer:
            raise ValueError("Bluetooth MAC address required for client")
        address = ((peer if mode == "connect" else "00:00:00:00:00:00"), port)
    else:
        raise ValueError("unknown transport")

    sock = socket.socket(family, socket.SOCK_STREAM, proto)
    if transport == "tcp" and mode == "listen":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if mode == "connect":
        try:
            sock.settimeout(CONNECT_TIMEOUT_SECONDS)
            sock.connect(address)
            sock.settimeout(None)
            return sock
        except BaseException:
            sock.close()
            raise
    try:
        sock.bind(address)
        sock.listen(1)
        connection, _peer_addr = sock.accept()
        return connection
    finally:
        sock.close()
