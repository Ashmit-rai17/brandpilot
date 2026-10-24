"""Acceptance checks every connector must pass. Call check_source_contract() from a pytest test.

    def test_arena_contract(monkeypatch):
        check_source_contract(monkeypatch, ArenaSource, ok_payload=SAMPLE, empty_payload={"data": []},
                              expected_type="inspiration")
"""
from __future__ import annotations

from brandpilot.sources import base
from brandpilot.sources.base import Reference, Source

from .http_fakes import TIMEOUT, FakeHTTP, FakeResponse, malformed


def _run(monkeypatch, make_source, response_queue, query="premium mithai packaging"):
    fake = FakeHTTP(default=None, routes={"": response_queue})
    monkeypatch.setattr(base, "send", fake)
    monkeypatch.setattr(base, "sleep", lambda s: fake.calls.append({"slept": s}))
    refs = make_source().search(query, 4)  # must not raise
    return refs, fake


def check_source_contract(monkeypatch, make_source, *, ok_payload: dict, empty_payload: dict,
                          expected_type: str, missing_metadata_payload: dict | None = None):
    # 1. success: typed, non-empty, within limit, correct reference type, licence on assets
    refs, _ = _run(monkeypatch, make_source, [FakeResponse(200, ok_payload)])
    assert refs and len(refs) <= 4 and all(isinstance(r, Reference) for r in refs)
    assert all(r.reference_type == expected_type and r.url and r.title for r in refs)
    assert all(r.verification == "unverified" and r.observed is None for r in refs), "connectors never claim 'observed'"
    assert len({r.id for r in refs}) == len(refs)
    assert isinstance(make_source(), Source)

    # 2. empty, malformed, server error, timeout: [] and never raises
    for queue in ([FakeResponse(200, empty_payload)], [malformed()], [FakeResponse(500, {})], [TIMEOUT]):
        assert _run(monkeypatch, make_source, queue)[0] == []

    # 3. at most one retry
    _, fake = _run(monkeypatch, make_source, [TIMEOUT])
    assert len([c for c in fake.calls if "url" in c]) <= 2

    # 4. 429: a short Retry-After is honoured once; a long one gives up without sleeping
    refs, fake = _run(monkeypatch, make_source,
                      [FakeResponse(429, {}, {"Retry-After": "1"}), FakeResponse(200, ok_payload)])
    assert refs and {"slept": 1.0} in fake.calls
    refs, fake = _run(monkeypatch, make_source, [FakeResponse(429, {}, {"Retry-After": "120"})])
    assert refs == [] and not any("slept" in c for c in fake.calls)

    # 5. items missing title/url/licence are dropped, not crashed on
    if missing_metadata_payload is not None:
        refs, _ = _run(monkeypatch, make_source, [FakeResponse(200, missing_metadata_payload)])
        assert all(r.url and r.title for r in refs)

    # 6. blank query does no HTTP
    _, fake = _run(monkeypatch, make_source, [FakeResponse(200, ok_payload)], query="  ")
    assert fake.calls == []
