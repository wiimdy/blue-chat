# blue-chat — Matterbridge Bluetooth text relay

> **Current status: Offline/localhost integration verified. Linux Bluetooth RFCOMM transport implemented but NOT tested with actual Bluetooth hardware or a live Mattermost server.** This is a proof of concept, not a production-ready secure messenger.

A minimal, **text-only** chat relay for two independently operated Matterbridge instances. Each site talks only to its own chat service and the local Matterbridge HTTP API. The relay agents exchange framed JSON messages over an **explicitly approved** Bluetooth RFCOMM connection. For local testing, a TCP connection is restricted to `127.0.0.1`.

```text
[Chat server A] <-> [Matterbridge A] <-HTTP localhost-> [Agent A]
                                                        ||
                                          Bluetooth Classic RFCOMM
                                                        ||
[Chat server B] <-> [Matterbridge B] <-HTTP localhost-> [Agent B]
```

## What's implemented

- Linux RFCOMM client and listener using Python `socket.AF_BLUETOOTH` / `BTPROTO_RFCOMM` (not yet hardware-tested).
- Localhost-only TCP transport for development and integration tests; **no external TCP listener**.
- Configurable local Matterbridge API client (`GET /api/messages`, `POST /api/message`) authenticated using a token from an environment variable.
- Text-only UTF-8 JSON protocol, 4-byte big-endian length prefix and 64 KiB frame cap.
- SQLite-backed outbound messages, ACK/retry and inbound message-ID deduplication.
- Simple relay username marker and optional exact sender/user-ID ignore rules to reduce echo loops.
- 14 automated unit and offline integration tests, including **real TCP loopback and HTTP mock servers**.

## Quick test (requires Python 3.11+)

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 scripts/offline_demo.py
```

The test suite does **not** require Bluetooth hardware, credentials, or a Matterbridge installation.

## Matterbridge configuration

See [`examples/matterbridge.toml.example`](examples/matterbridge.toml.example). In each site, configure its Mattermost account plus a **distinct locally bound** `[api.local]` instance. Use the original Matterbridge API implementation for exact version compatibility: [`bridge/api/api.go`](https://github.com/42wim/matterbridge/blob/master/bridge/api/api.go).

Set the local API token via environment variable (never commit credentials):

```bash
export MATTERBRIDGE_API_TOKEN='CHOOSE_THE_SITE_LOCAL_API_TOKEN'
```

Only one consumer should read `GET /api/messages` on each site because **reading removes messages from Matterbridge's in-memory ring buffer**. As a result, a crash between fetching an event and storing it in SQLite can lose that event. This PoC does **not** guarantee zero loss or exactly-once delivery. ACK means the destination's local Matterbridge API returned success, not that all downstream chat clients received the post.

## Run two agents on the same computer (development)

Start a Matterbridge instance for each side with **different** local API ports, tokens and SQLite files. Then open two terminals:

```bash
# A (listen) — only binds 127.0.0.1
python3 -m matterbridge_bt_relay.cli listen \
  --transport tcp --port 8765 --origin inside \
  --api-url http://127.0.0.1:4242 --db a.sqlite3 \
  --ignore-sender matterbridge
```

```bash
# B (connect)
python3 -m matterbridge_bt_relay.cli connect \
  --transport tcp --peer 127.0.0.1 --port 8765 --origin outside \
  --api-url http://127.0.0.1:4243 --db b.sqlite3 \
  --ignore-sender matterbridge
```

Each process needs its own `MATTERBRIDGE_API_TOKEN`; the two site tokens may differ. The TCP mode is **local-only** and not an IP bridge between two machines.

## Linux Bluetooth RFCOMM hardware trial (only on permitted devices)

Bluetooth Classic RFCOMM is currently implemented for Linux only, using the standard-library socket API. Pair two Linux systems with compatible adapters through normal operating-system procedures, confirm Bluetooth serial/RFCOMM support, and only then use the following commands. One process on each system:

```bash
# Device A
python3 -m matterbridge_bt_relay.cli listen \
  --transport rfcomm --port 3 --origin inside \
  --api-url http://127.0.0.1:4242 --db inside.sqlite3
```

```bash
# Device B, replace address with approved device A Bluetooth MAC
python3 -m matterbridge_bt_relay.cli connect \
  --transport rfcomm --peer AA:BB:CC:DD:EE:FF --port 3 --origin outside \
  --api-url http://127.0.0.1:4242 --db outside.sqlite3
```

This assumes Bluetooth access, proper pairing, service availability and Matterbridge instances already configured on each device. **No actual Bluetooth link was tested here.** macOS/Windows support is not implemented by this project yet (a separate transport adapter is required).

## Operation and safety

- **Obtain written approval** for Bluetooth device-to-device communication in any separated/restricted network environment. RFCOMM is still a direct device connection, even though it carries no IP packets in this project.
- This tool intentionally excludes IP forwarding, proxies, tunneling, command execution, remote control, files and arbitrary network payloads.
- Avoid sensitive text until peer authentication/encryption, channel policy, message integrity and retention are reviewed. Classic Bluetooth pairing alone is not a blanket security guarantee.
- Supply distinct `--origin` values on the two devices and the same `--channel`. Use `--ignore-sender` and/or `--ignore-userid` for the source-side Matterbridge/Mattermost bot identity to prevent loops. Only configure the intended channel in the Matterbridge gateway.
- SQLite files contain message content in plaintext. Protect their file system permissions and purge after tests.
- The API polling endpoint is destructive, so messages may be lost during process crashes; destination retries can also lead to duplicates if a POST succeeds just before the process crashes.

## Layout

```text
src/matterbridge_bt_relay/
  protocol.py        Message framing and schema
  transport.py       Framed sockets, ACKs and TCP/RFCOMM connectors
  matterbridge_api.py  Localhost-only Matterbridge API adapter
  relay.py           Bidirectional relay engine
  outbox.py          SQLite outbound/inbound message ledger
  cli.py             Linux RFCOMM and localhost TCP entry point
scripts/offline_demo.py
examples/matterbridge.toml.example
tests/                 Unit and offline end-to-end tests
docs/                  Architecture and development plan
.github/workflows/tests.yml
```

## Roadmap

See [`docs/implementation-plan.md`](docs/implementation-plan.md). Next real milestones: Linux Bluetooth pair test, live Matterbridge API test, reconnect under Bluetooth signal loss, reliable deduplication after process crashes, and authenticated peer protocol. None is claimed complete yet.
