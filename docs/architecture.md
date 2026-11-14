# blue-chat architecture and trust boundaries

## Scope

```
Chat server A ⇄ Matterbridge A ⇄ API (loopback) ⇄ Agent A
                                                    ⇅ RFCOMM (approved)
Chat server B ⇄ Matterbridge B ⇄ API (loopback) ⇄ Agent B
```

- Agents never open a network tunnel or relay arbitrary IP traffic.
- Standard Python Linux RFCOMM socket is provided, but hardware compatibility is unverified.
- Local development uses `127.0.0.1` TCP only, with redirects/proxy configuration disabled on Matterbridge HTTP clients.
- Only the configured Matterbridge gateway's event stream and a single preapproved logical channel should be used.

## On-wire protocol

Message: `[4-byte network-order payload length][UTF-8 JSON]` with the fields `id`, `origin`, `channel`, `sender`, `text`, `timestamp`; maximum payload 64 KiB; relay text limit 8,000 UTF-8 bytes. ACK: similarly framed JSON `{"type":"ack","id":"<uuid>"}`. Each device uses its own distinct origin tag. No credentials are included in frames.

The local `--gateway` name is included in destination HTTP POSTs and filters source events. It defaults to `blue-chat-local`. This is distinct from the logical `--channel` shared by the two agents. Matterbridge may acknowledge an HTTP POST while dropping its route if the gateway name is incorrect.

## SQLite durability

Outbox persists pending messages until an ACK is received. The receiver persists message IDs and marks them as posted after the local Matterbridge API returns HTTP 2xx. Received ACKs mark the sender's messages done. Resending is possible after reconnection.

Malformed source events are skipped individually so later valid events in the same destructive poll are still persisted. Session shutdown waits for its receiver's active HTTP request before another session starts or the database closes. Transient connection attempts have a 10-second timeout.

**Limits of guarantees:** Matterbridge `/api/messages` is an in-memory destructive queue. Its events can be lost around process crashes. A receiver can also crash between successful HTTP POST and the SQLite posted mark, causing duplicate delivery after retry. Exactly-once and lossless end-to-end delivery are **not provided**.

## Loop prevention

Each injected message uses a visible `[blue-chat/<origin>] <sender>` username, ignored upon subsequent polling. Administrators should additionally configure `--ignore-sender` or `--ignore-userid` for the local chat bridge bot. Exact display names depend on chat platform behavior; verify on a test channel before live use.

## Security constraints

- Only localhost Matterbridge API URLs are accepted. HTTP redirects and ambient HTTP proxies are disabled.
- API credentials are read from a local environment variable. Do not send them via RFCOMM or commit secrets to Git.
- Peer authentication, cryptographic message integrity, encrypted SQLite storage and robust retention policy are **not** yet implemented; use dummy content on trusted paired devices only.
- Bluetooth RFCOMM still establishes a direct communication link. Any permitted use in a segmented network depends on written authorization from the operator/competition organizer.
