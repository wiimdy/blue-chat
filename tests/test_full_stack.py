"""Real loopback TCP + two HTTP API servers + two relay engines."""

import json
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from matterbridge_bt_relay.matterbridge_api import MatterbridgeAPI
from matterbridge_bt_relay.outbox import Outbox
from matterbridge_bt_relay.relay import RelaySession
from matterbridge_bt_relay.transport import PacketSocket, open_socket


class MockMatterbridge:
    def __init__(self):
        self.queue = []
        self.posts = []
        self.unrouted = []
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer shared-test":
                    self.send_error(401)
                    return
                if self.path != "/api/messages":
                    self.send_error(404)
                    return
                with owner.lock:
                    values = owner.queue
                    owner.queue = []
                self.respond(values)

            def do_POST(self):
                if self.headers.get("Authorization") != "Bearer shared-test":
                    self.send_error(401)
                    return
                if self.path != "/api/message":
                    self.send_error(404)
                    return
                msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with owner.lock:
                    # Matterbridge returns success even when a missing/wrong
                    # gateway prevents delivery to a destination channel.
                    if msg.get("gateway") == "blue-chat-local":
                        owner.posts.append(msg)
                        owner.queue.append(
                            {
                                "protocol": "mattermost",
                                "username": msg["username"],
                                "text": msg["text"],
                                "gateway": "blue-chat-local",
                            }
                        )
                    else:
                        owner.unrouted.append(msg)
                self.respond(msg)

            def respond(self, doc):
                payload = json.dumps(doc, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def push(self, user, text):
        with self.lock:
            self.queue.append(
                {
                    "protocol": "mattermost",
                    "username": user,
                    "text": text,
                    "gateway": "blue-chat-local",
                }
            )

    def posted(self):
        with self.lock:
            return list(self.posts)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def eventually(condition, timeout=4.0):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


class FullStackTests(unittest.TestCase):
    def test_two_real_http_clients_over_local_tcp(self):
        source, dest = MockMatterbridge(), MockMatterbridge()
        try:
            # Open a real TCP listener and connect through the same transport
            # factory used by the CLI (localhost only).
            srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv_sock.bind(("127.0.0.1", 0))
            port = srv_sock.getsockname()[1]
            srv_sock.close()
            accepted = []

            def accept():
                accepted.append(
                    open_socket(mode="listen", transport="tcp", peer=None, port=port)
                )

            listener = threading.Thread(target=accept, daemon=True)
            listener.start()
            time.sleep(0.03)
            client_socket = open_socket(
                mode="connect", transport="tcp", peer="127.0.0.1", port=port
            )
            listener.join(timeout=2)
            self.assertEqual(len(accepted), 1)
            with tempfile.TemporaryDirectory() as directory:
                with (
                    Outbox(Path(directory) / "a.db") as a_store,
                    Outbox(Path(directory) / "b.db") as b_store,
                ):
                    a = RelaySession(
                        api=MatterbridgeAPI(source.url, "shared-test"),
                        store=a_store,
                        transport=PacketSocket(accepted[0]),
                        origin="inside",
                        channel="general",
                        poll_interval=0.02,
                        retry_interval=0.08,
                    )
                    b = RelaySession(
                        api=MatterbridgeAPI(dest.url, "shared-test"),
                        store=b_store,
                        transport=PacketSocket(client_socket),
                        origin="outside",
                        channel="general",
                        poll_interval=0.02,
                        retry_interval=0.08,
                    )
                    threads = [
                        threading.Thread(target=x.run, daemon=True) for x in (a, b)
                    ]
                    for t in threads:
                        t.start()
                    try:
                        source.push("alice", "Bluetooth 대신 TCP 실험")
                        eventually(lambda: len(dest.posted()) == 1)
                        self.assertEqual(
                            dest.posted()[0]["text"], "Bluetooth 대신 TCP 실험"
                        )
                        eventually(lambda: not a_store.pending())
                        dest.push("bob", "실제 REST API 호출 성공")
                        eventually(lambda: len(source.posted()) == 1)
                        eventually(lambda: not b_store.pending())
                        time.sleep(0.2)
                        self.assertEqual(len(dest.posted()), 1)
                        self.assertEqual(len(source.posted()), 1)
                    finally:
                        for x in [a, b]:
                            x.stop.set()
                        for x in [a, b]:
                            x.transport.close()
                        for t in threads:
                            t.join(timeout=2)
        finally:
            source.close()
            dest.close()
