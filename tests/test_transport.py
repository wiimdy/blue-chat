import socket
import struct
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from matterbridge_bt_relay.protocol import MAX_PAYLOAD_BYTES, Message
from matterbridge_bt_relay.transport import Ack, PacketSocket, decode_packet, encode_packet, open_socket


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
