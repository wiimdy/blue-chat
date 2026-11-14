"""CLI configuration failures must not enter the reconnect loop."""
import contextlib
import io
import os
import unittest
from unittest.mock import patch

from matterbridge_bt_relay.cli import main


class CLITests(unittest.TestCase):
    def run_invalid(self, arguments, expected):
        with (patch.dict(os.environ, {"MATTERBRIDGE_API_TOKEN": "test-token"}),
              patch("sys.argv", ["blue-chat", "connect", "--origin", "A", *arguments]),
              patch("matterbridge_bt_relay.cli.Outbox") as store,
              patch("matterbridge_bt_relay.cli.open_socket", side_effect=ValueError("bad configuration")),
              patch("matterbridge_bt_relay.cli.time.sleep", side_effect=KeyboardInterrupt),
              contextlib.redirect_stderr(io.StringIO()) as stderr):
            with self.assertRaises(SystemExit) as raised:
                main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn(expected, stderr.getvalue())
            store.assert_not_called()

    def test_empty_origin_fails_before_opening_database(self):
        self.run_invalid(["--origin", ""], "origin")

    def test_empty_channel_fails_before_opening_database(self):
        self.run_invalid(["--channel", " "], "channel")

    def test_remote_tcp_peer_fails_before_opening_database(self):
        self.run_invalid(["--peer", "192.0.2.1"], "localhost")

    def test_invalid_api_url_is_reported_as_configuration_error(self):
        self.run_invalid(["--api-url", "http://127.0.0.1:invalid"], "port")

    def test_empty_gateway_fails_before_opening_database(self):
        self.run_invalid(["--gateway", ""], "gateway")

    def test_missing_rfcomm_peer_fails_before_opening_database(self):
        self.run_invalid(["--transport", "rfcomm", "--port", "3"], "peer")

    def test_permanent_transport_error_does_not_retry(self):
        with (patch.dict(os.environ, {"MATTERBRIDGE_API_TOKEN": "test-token"}),
              patch("sys.argv", ["blue-chat", "connect", "--origin", "A"]),
              patch("matterbridge_bt_relay.cli.Outbox"),
              patch("matterbridge_bt_relay.cli.open_socket", side_effect=RuntimeError("unsupported platform")),
              patch("matterbridge_bt_relay.cli.time.sleep", side_effect=KeyboardInterrupt) as sleep,
              contextlib.redirect_stderr(io.StringIO()) as stderr):
            with self.assertRaises(SystemExit) as raised:
                main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("unsupported platform", stderr.getvalue())
            sleep.assert_not_called()

    def test_default_gateway_and_rfcomm_channel_reach_dependencies(self):
        with (patch.dict(os.environ, {"MATTERBRIDGE_API_TOKEN": "test-token"}),
              patch("sys.argv", ["blue-chat", "connect", "--origin", "A",
                                  "--transport", "rfcomm", "--peer", "AA:BB:CC:DD:EE:FF"]),
              patch("matterbridge_bt_relay.cli.Outbox"),
              patch("matterbridge_bt_relay.cli.MatterbridgeAPI") as api,
              patch("matterbridge_bt_relay.cli.open_socket") as connect,
              patch("matterbridge_bt_relay.cli.PacketSocket"),
              patch("matterbridge_bt_relay.cli.RelaySession") as session):
            session.return_value.run.side_effect = KeyboardInterrupt
            self.assertEqual(main(), 0)
            self.assertEqual(api.call_args.kwargs["gateway"], "blue-chat-local")
            self.assertEqual(session.call_args.kwargs["gateway"], "blue-chat-local")
            self.assertEqual(connect.call_args.kwargs["port"], 3)

    def test_temporary_connection_failure_retries(self):
        with (patch.dict(os.environ, {"MATTERBRIDGE_API_TOKEN": "test-token"}),
              patch("sys.argv", ["blue-chat", "connect", "--origin", "A"]),
              patch("matterbridge_bt_relay.cli.Outbox"),
              patch("matterbridge_bt_relay.cli.open_socket", side_effect=[OSError("refused"), KeyboardInterrupt]) as connect,
              patch("matterbridge_bt_relay.cli.time.sleep") as sleep):
            self.assertEqual(main(), 0)
            self.assertEqual(connect.call_count, 2)
            sleep.assert_called_once_with(2)
