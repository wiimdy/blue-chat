# Implementation & verification checklist

## Implemented, validated locally

- [x] UTF-8 JSON, big-endian 4-byte frame format, strict maximum size
- [x] Message and ACK packet parsing over partial reads
- [x] SQLite outbound queue, ACK and receiver deduplication ledger
- [x] Matterbridge localhost HTTP API polling and posts with token
- [x] Bidirectional relay engine, basic echo filtering and retries
- [x] Linux RFCOMM socket transport implementation (NOT hardware-tested)
- [x] TCP loopback-only test transport
- [x] Offline integration with mock HTTP APIs, real TCP loopback sockets
- [x] GitHub Actions test workflow added (not yet run on GitHub)

## Unverified / not implemented

- [ ] Written approval for a Bluetooth link in the intended environment
- [ ] Linux adapter and OS pairing capability for RFCOMM channel
- [ ] Real A↔B RFCOMM transfer and 100-message stress test
- [ ] Actual Matterbridge server + Mattermost/Slack API compatibility
- [ ] Verify bot message suppression on the actual chat service
- [ ] Host reboot/connection loss and reliable queue recovery validation
- [ ] More robust integrity/authentication (e.g., application-layer MAC)
- [ ] Correct recovery from destructive Matterbridge polling around crashes
- [ ] Exactly-once posting safeguards and retention/cleanup
- [ ] macOS/Windows Bluetooth transport implementation

## Acceptance tests on authorized hardware

1. Both devices have distinct `--origin` and same `--channel`.
2. Each Matterbridge API is accessible only on its local loopback interface.
3. A and B exchange 100 Unicode text messages each direction without unintentional duplicate posts.
4. Disconnect and reconnect the approved Bluetooth link and verify pending outbox delivery.
5. Verify that unrelated Mattermost channels and bridge bot output are not mirrored.
6. Capture logs to verify no token or message text leaks, and test shutdown/restart.

**Status**: Local transport/API integration tests pass. Real hardware and live-service tests remain blocked on access to two devices/servers.
