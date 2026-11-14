"""Exercise actual CLI processes, HTTP, TCP and persistent SQLite together."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TextIO

from test_full_stack import MockMatterbridge, eventually

MESSAGE_COUNT = 100


@unittest.skipIf(sys.platform == "win32", "CLI shutdown test uses POSIX SIGINT")
class CLIEndToEndTests(unittest.TestCase):
    def test_bidirectional_burst_and_peer_restart(self) -> None:
        source, destination = MockMatterbridge(), MockMatterbridge()
        processes: list[subprocess.Popen] = []
        logs: list[TextIO] = []
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    port = reservation.getsockname()[1]

                def start(mode: str, origin: str, api_url: str) -> subprocess.Popen:
                    log = (root / f"{origin}-{len(logs)}.log").open("w+")
                    logs.append(log)
                    env = dict(os.environ)
                    env["MATTERBRIDGE_API_TOKEN"] = "shared-test"
                    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "matterbridge_bt_relay.cli",
                            mode,
                            "--transport",
                            "tcp",
                            "--port",
                            str(port),
                            "--origin",
                            origin,
                            "--api-url",
                            api_url,
                            "--db",
                            str(root / f"{origin}.db"),
                        ],
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                    processes.append(process)
                    return process

                def stop(process: subprocess.Popen) -> None:
                    process.send_signal(signal.SIGINT)
                    self.assertEqual(process.wait(timeout=10), 0)

                # Starting the client first exercises connection retry too.
                peer = start("connect", "outside", destination.url)
                listener = start("listen", "inside", source.url)
                expected_outside = [
                    f"from Alice {index}: 안녕하세요 🛰"
                    for index in range(MESSAGE_COUNT)
                ]
                expected_inside = [
                    f"from Bob {index}: 반갑습니다 🌍" for index in range(MESSAGE_COUNT)
                ]
                for text in expected_outside:
                    source.push("alice", text)
                for text in expected_inside:
                    destination.push("bob", text)
                eventually(
                    lambda: len(destination.posted()) == MESSAGE_COUNT, timeout=20
                )
                eventually(lambda: len(source.posted()) == MESSAGE_COUNT, timeout=20)
                self.assertEqual(
                    [post["text"] for post in destination.posted()], expected_outside
                )
                self.assertEqual(
                    [post["text"] for post in source.posted()], expected_inside
                )

                stop(peer)
                source.push("alice", "queued while peer was offline")
                peer = start("connect", "outside", destination.url)
                eventually(
                    lambda: len(destination.posted()) == MESSAGE_COUNT + 1, timeout=15
                )
                self.assertEqual(
                    destination.posted()[-1]["text"], "queued while peer was offline"
                )
                destination.push("bob", "reply after restart")
                eventually(
                    lambda: len(source.posted()) == MESSAGE_COUNT + 1, timeout=10
                )
                self.assertEqual(source.posted()[-1]["text"], "reply after restart")
                self.assertEqual(source.unrouted + destination.unrouted, [])
                stop(peer)
                stop(listener)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            output = ""
            for log in logs:
                log.seek(0)
                output += log.read()
                log.close()
            source.close()
            destination.close()
            self.assertNotIn("Traceback", output, output)
