"""Fake HTTP for source connectors. Patch brandpilot.sources.base.send with a FakeHTTP instance."""
from __future__ import annotations

import json as _json

import requests


class FakeResponse:
    def __init__(self, status: int = 200, body=None, headers: dict | None = None, raw: bytes | None = None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.content = raw if raw is not None else (b"" if body is None else _json.dumps(body).encode())

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self):
        if self._body is None:
            return _json.loads(self.content.decode() or "x")  # raises ValueError like requests
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


TIMEOUT = object()  # queue this to simulate requests.Timeout


class FakeHTTP:
    """Routes by URL substring to a queue of responses; the last response repeats. Records every call."""

    def __init__(self, routes: dict[str, list] | None = None, default=None):
        self.routes = {k: list(v) for k, v in (routes or {}).items()}
        self.default = default
        self.calls: list[dict] = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        queue = next((q for k, q in self.routes.items() if k in url), None)
        item = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else self.default
        if item is TIMEOUT:
            raise requests.Timeout("fake timeout")
        if item is None:
            raise requests.ConnectionError(f"no fake route for {url}")
        return item


def malformed() -> FakeResponse:
    return FakeResponse(200, raw=b"<html>not json")
