"""Small localhost-only client for matterbridge's documented API.

GET /api/messages is destructive, so run exactly one reader and persist
messages immediately. It is *not* a lossless source under process crashes.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        # A local service must never redirect an API token to another host.
        return None


class MatterbridgeAPI:
    def __init__(self, base_url: str, token: str, *, timeout: float = 3.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Matterbridge API must be bound to localhost HTTP")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("invalid localhost API URL")
        if not token:
            raise ValueError("Matterbridge API token must not be empty")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        # Ignore machine HTTP_PROXY environment variables; never leave loopback.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, path: str, payload: dict | None = None) -> object:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = Request(self.base_url + path, data=data)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with self._opener.open(req, timeout=self.timeout) as result:
            # Prevent a misconfigured service from exhausting the process.
            blob = result.read(2 * 1024 * 1024 + 1)
            if len(blob) > 2 * 1024 * 1024:
                raise ValueError("Matterbridge response too large")
            return json.loads(blob)

    def get_messages(self) -> list[dict]:
        result = self._request("/api/messages")
        if result is None:
            return []
        if not isinstance(result, list):
            raise ValueError("unexpected Matterbridge messages response")
        return [msg for msg in result if isinstance(msg, dict)]

    def post_message(self, *, origin: str, sender: str, text: str) -> None:
        # Identifiable relay username is used to suppress return-path echoes.
        self._request("/api/message", {
            "username": f"[blue-chat/{origin}] {sender}",
            "text": text,
        })
