import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from matterbridge_bt_relay.matterbridge_api import MatterbridgeAPI


class APITests(unittest.TestCase):
    def test_localhost_guard(self):
        with self.assertRaises(ValueError):
            MatterbridgeAPI("https://remote.example", "token")
        with self.assertRaises(ValueError):
            MatterbridgeAPI("http://192.168.1.4:4242", "token")
        with self.assertRaises(ValueError):
            MatterbridgeAPI("http://127.0.0.1:4242", "")

    def test_http_api_integration(self):
        posted = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer secret":
                    self.send_error(401); return
                body = b'[{"protocol":"mattermost","text":"hello","username":"alice"}]'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                if self.headers.get("Authorization") != "Bearer secret":
                    self.send_error(401); return
                posted.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        try:
            api = MatterbridgeAPI(f"http://127.0.0.1:{server.server_port}", "secret")
            self.assertEqual(api.get_messages()[0]["text"], "hello")
            api.post_message(origin="A", sender="alice", text="안녕")
            self.assertEqual(posted, [{"username": "[blue-chat/A] alice", "text": "안녕"}])
        finally:
            server.shutdown()
            server.server_close()
            runner.join(timeout=2)
