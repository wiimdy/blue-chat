"""Verify routing against a local Matterbridge binary, without chat credentials."""

from __future__ import annotations

import argparse
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError

from matterbridge_bt_relay.matterbridge_api import MatterbridgeAPI


def verify(binary: Path) -> None:
    """Start two loopback API accounts and verify actual gateway routing."""
    with socket.socket() as first, socket.socket() as second:
        first.bind(("127.0.0.1", 0))
        second.bind(("127.0.0.1", 0))
        local_port = first.getsockname()[1]
        observer_port = second.getsockname()[1]

    token = secrets.token_hex(16)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = root / "matterbridge.toml"
        config.write_text(
            f'''[api.local]
BindAddress = "127.0.0.1:{local_port}"
Token = "{token}"
Buffer = 100
[api.observer]
BindAddress = "127.0.0.1:{observer_port}"
Token = "{token}"
Buffer = 100
[[gateway]]
name = "blue-chat-local"
enable = true
[[gateway.inout]]
account = "api.local"
channel = "api"
[[gateway.inout]]
account = "api.observer"
channel = "api"
''',
            encoding="utf-8",
        )
        with (root / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [str(binary.resolve()), "-conf", str(config)], stdout=log, stderr=log
            )
            try:
                sender = MatterbridgeAPI(f"http://127.0.0.1:{local_port}", token)
                observer = MatterbridgeAPI(f"http://127.0.0.1:{observer_port}", token)
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(f"Matterbridge exited: {log.read()}")
                    try:
                        sender.get_messages()
                        observer.get_messages()
                        break
                    except URLError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.05)

                # Old payloads get HTTP 200 but never reach the observer.
                sender._request("/api/message", {"username": "alice", "text": "unrouted"})
                sender.post_message(origin="inside", sender="alice", text="안녕하세요 🛰")
                deadline = time.monotonic() + 5
                messages: list[dict] = []
                while time.monotonic() < deadline and not messages:
                    messages.extend(observer.get_messages())
                    time.sleep(0.05)
                if len(messages) != 1 or messages[0].get("text") != "안녕하세요 🛰":
                    raise AssertionError(f"Unexpected routed messages: {messages!r}")
                if messages[0].get("username") != "[blue-chat/inside] alice":
                    raise AssertionError("Relay username marker was not preserved")
                if messages[0].get("gateway") != "blue-chat-local":
                    raise AssertionError("Unexpected destination gateway")
                print("PASS: real Matterbridge routes Unicode text and preserves relay marker")
                print("PASS: old payload without gateway returns success but is not delivered")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="path to the Matterbridge executable")
    verify(parser.parse_args().binary)
