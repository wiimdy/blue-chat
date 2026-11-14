"""Run a deliberately text-only relay between two approved devices."""
from __future__ import annotations

import argparse
import logging
import os
import time

from .matterbridge_api import DEFAULT_GATEWAY, MatterbridgeAPI
from .outbox import Outbox
from .relay import RelaySession
from .transport import PacketSocket, open_socket


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorized text-only Matterbridge Bluetooth relay")
    parser.add_argument("mode", choices=["listen", "connect"])
    parser.add_argument("--transport", choices=["tcp", "rfcomm"], default="tcp")
    parser.add_argument("--peer", help="Bluetooth MAC (connect) or 127.0.0.1 for TCP test")
    parser.add_argument("--port", type=int, default=None, help="TCP port (default 8765) or RFCOMM channel (default 3)")
    parser.add_argument("--origin", required=True, help="unique local site identifier")
    parser.add_argument("--channel", default="general", help="approved logical channel")
    parser.add_argument("--api-url", default="http://127.0.0.1:4242")
    parser.add_argument("--token-env", default="MATTERBRIDGE_API_TOKEN")
    parser.add_argument("--db", default="blue-chat.sqlite3")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY,
                        help="local Matterbridge gateway for filtering and posting (default blue-chat-local)")
    parser.add_argument("--ignore-sender", action="append", default=[], help="exact sender to suppress")
    parser.add_argument("--ignore-userid", action="append", default=[], help="source bot user ID to suppress")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not args.origin.strip():
        parser.error("origin must not be empty")
    if not args.channel.strip():
        parser.error("channel must not be empty")
    if not args.gateway.strip():
        parser.error("gateway must not be empty")
    if args.transport == "tcp" and args.peer not in {None, "127.0.0.1", "localhost"}:
        parser.error("TCP development peer must stay on localhost")
    if args.transport == "rfcomm" and args.mode == "connect" and not args.peer:
        parser.error("RFCOMM connect requires --peer Bluetooth MAC address")
    if args.port is None:
        args.port = 3 if args.transport == "rfcomm" else 8765
    if args.transport == "rfcomm" and not 1 <= args.port <= 30:
        parser.error("RFCOMM channel must be 1..30")
    if args.transport == "tcp" and not 0 < args.port < 65536:
        parser.error("TCP port must be 1..65535")
    token = os.getenv(args.token_env, "")
    if not token:
        parser.error(f"set {args.token_env} before connecting to the Matterbridge API")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        api = MatterbridgeAPI(args.api_url, token, gateway=args.gateway)
    except ValueError as exc:
        parser.error(str(exc))
    with Outbox(args.db) as store:
        try:
            while True:
                try:
                    connection = open_socket(mode=args.mode, transport=args.transport,
                                             peer=args.peer, port=args.port)
                except (RuntimeError, ValueError) as exc:
                    parser.error(str(exc))
                except OSError as exc:
                    logging.error("connection failed (%s); retrying", exc)
                    time.sleep(2)
                    continue
                logging.info("connected (%s)", args.transport)
                session = RelaySession(api=api, store=store,
                                       transport=PacketSocket(connection),
                                       origin=args.origin, channel=args.channel,
                                       gateway=args.gateway,
                                       ignored_senders=frozenset(args.ignore_sender),
                                       ignored_userids=frozenset(args.ignore_userid))
                session.run()
                logging.info("connection ended; reconnecting")
                time.sleep(2)
        except KeyboardInterrupt:
            logging.info("shutting down")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
