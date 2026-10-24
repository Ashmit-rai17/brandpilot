"""The shared source contract, exercised through a minimal reference connector."""
import pytest
from pydantic import ValidationError

from brandpilot.sources import base
from brandpilot.sources.base import Observed, Reference, Source, ref_id, request_json

from .http_fakes import FakeHTTP, FakeResponse
from .source_contract import check_source_contract


class EchoSource(Source):
    """Smallest valid connector: one GET, maps items to inspiration references."""
    name = "echo"

    def _search(self, query, limit):
        data = request_json("GET", "https://example.test/search", params={"q": query}, timeout=self.timeout)
        out = []
        for item in (data or {}).get("items", []):
            if isinstance(item, dict) and item.get("url") and item.get("title"):
                out.append(Reference(id=ref_id(self.name, item["url"]), source=self.name, title=item["title"],
                                     url=item["url"], reference_type="inspiration"))
        return out[:limit]


OK = {"items": [{"title": f"Case study {i}", "url": f"https://example.test/{i}"} for i in range(6)]}


def test_reference_connector_passes_contract(monkeypatch):
    check_source_contract(monkeypatch, EchoSource, ok_payload=OK, empty_payload={"items": []},
                          expected_type="inspiration",
                          missing_metadata_payload={"items": [{"title": "no url"}, {"url": "https://x.test"}, 7]})


def test_crashing_connector_returns_empty():
    class Broken(Source):
        def _search(self, query, limit):
            raise KeyError("boom")
    assert Broken().search("anything") == []


def test_disabled_source_does_no_http(monkeypatch):
    fake = FakeHTTP(default=FakeResponse(200, OK))
    monkeypatch.setattr(base, "send", fake)

    class NoKey(EchoSource):
        def enabled(self):
            return False
    assert NoKey().search("coffee") == [] and fake.calls == []


def test_user_agent_is_descriptive(monkeypatch):
    fake = FakeHTTP(default=FakeResponse(200, OK))
    monkeypatch.setattr(base, "send", fake)
    request_json("GET", "https://example.test", timeout=1)
    assert fake.calls[0]["headers"]["User-Agent"] == "BrandPilot/0.1 (https://github.com/Ashmit-rai17/brandpilot)"


def test_asset_requires_licence():
    with pytest.raises(ValidationError):
        Reference(id="x", source="openverse", title="t", url="https://x", reference_type="asset")


def test_observed_and_verification_must_agree():
    obs = Observed(palette=[{"hex": "#AA5500", "share": 0.6}], lightness=0.5, saturation=0.3, negative_space=0.7)
    with pytest.raises(ValidationError):
        Reference(id="x", source="s", title="t", url="https://x", reference_type="inspiration", observed=obs)
    with pytest.raises(ValidationError):
        Reference(id="x", source="s", title="t", url="https://x", reference_type="inspiration", verification="observed")
    ok = Reference(id="x", source="s", title="t", url="https://x", reference_type="inspiration",
                   observed=obs, verification="observed")
    assert ok.observed.palette[0].hex == "#AA5500"
