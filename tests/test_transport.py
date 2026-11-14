import json
import socket
import struct
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from matterbridge_bt_relay.protocol import MAX_PAYLOAD_BYTES, Message
from matterbridge_bt_relay.transport import (
    Ack,
    PacketSocket,
    decode_packet,
    encode_packet,
    open_socket,
)


class TransportTests(unittest.TestCase):
    def test_packet_socket_roundtrip_and_ack(self):
        left, right = socket.socketpair()
        try:
            sender, receiver = PacketSocket(left), PacketSocket(right)
            msg = Message.new(origin="A", channel="general", sender="alice", text="안녕하세요")
            sender.send(msg)
            self.assertEqual(receiver.receive(), msg)
            receiver.send(Ack(msg.id))
            self.assertEqual(sender.receive(), Ack(msg.id))
        finally:
            left.close()
            right.close()

    def test_split_frame_reads(self):
        left, right = socket.socketpair()
        try:
            receiver = PacketSocket(right)
            msg = Message.new(origin="A", channel="general", sender="bob", text="hello")
            payload = encode_packet(msg)
            for byte in payload[:-1]:
                left.sendall(bytes([byte]))
            left.sendall(payload[-1:])
            self.assertEqual(receiver.receive(), msg)
        finally:
            left.close()
            right.close()

    def test_invalid_ack_and_oversized_packet(self):
        with self.assertRaises(ValueError):
            decode_packet(struct.pack("!I", 0))
        with self.assertRaises(ValueError):
            decode_packet(struct.pack("!I", MAX_PAYLOAD_BYTES + 1))
        with self.assertRaises(ValueError):
            decode_packet(struct.pack("!I", 23) + b'{"type":"ack","id":"x"}')

    def test_tcp_nonlocal_forbidden(self):
        with self.assertRaises(ValueError):
            open_socket(mode="connect", transport="tcp", peer="192.168.1.1", port=3333)

    def test_decoder_reports_deep_json_as_invalid(self) -> None:
        payload = b"[" * 2000 + b"0" + b"]" * 2000
        with self.assertRaises(ValueError):
            decode_packet(struct.pack("!I", len(payload)) + payload)

    def test_invalid_ack_schema(self) -> None:
        for body in ({"type": "ack", "id": "invalid"},
                     {"type": "ack", "id": 42},
                     {"type": "ack", "id": str(uuid4()), "extra": True}):
            payload = json.dumps(body).encode("utf-8")
            with self.subTest(body=body), self.assertRaises(ValueError):
                decode_packet(struct.pack("!I", len(payload)) + payload)

    def test_partial_read_preserves_bytes_across_timeout(self) -> None:
        message = Message.new(origin="A", channel="general", sender="bob", text="hello")
        payload = encode_packet(message)
        sock = Mock()
        sock.recv.side_effect = [payload[:2], socket.timeout(), payload[2:4],
                                 payload[4:10], socket.timeout(), payload[10:]]
        self.assertEqual(PacketSocket(sock).receive(), message)

    def test_truncated_frame_reports_disconnection(self) -> None:
        sock = Mock()
        sock.recv.side_effect = [b"\x00\x00", b""]
        with self.assertRaises(EOFError):
            PacketSocket(sock).receive()

    def test_receive_stop_during_partial_frame(self) -> None:
        stop = threading.Event()
        sock = Mock()

        def receive(size: int) -> bytes:
            stop.set()
            return b"\x00"

        sock.recv.side_effect = receive
        with self.assertRaises(EOFError):
            PacketSocket(sock).receive(stop)

    def test_connect_has_bounded_timeout_and_restores_blocking_mode(self) -> None:
        with patch("matterbridge_bt_relay.transport.socket.socket") as make_socket:
            sock = make_socket.return_value
            self.assertIs(open_socket(mode="connect", transport="tcp",
                                      peer="localhost", port=3333), sock)
            self.assertEqual(sock.settimeout.call_args_list[0].args, (10.0,))
            self.assertEqual(sock.settimeout.call_args_list[-1].args, (None,))

    def test_failed_connect_closes_socket(self) -> None:
        with patch("matterbridge_bt_relay.transport.socket.socket") as make_socket:
            sock = make_socket.return_value
            sock.connect.side_effect = socket.timeout("unreachable")
            with self.assertRaises(socket.timeout):
                open_socket(mode="connect", transport="tcp", peer="localhost", port=3333)
            sock.close.assert_called_once()
