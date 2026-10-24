"""Shared contract for design-research sources. Change a field only after telling the other owner.

Two kinds of reference, never mixed:
  inspiration  a case study or design page (Behance, BP&O, Are.na...). Evidence for creative decisions only.
  asset        openly licensed media (Openverse, Wikimedia, Unsplash). Must carry a licence.

What a design looks like is only ever `observed` (computed by us from a preview image we downloaded).
Anything read from a title or snippet goes in `interpreted` and is labelled as text. A snippet is never proof.

Every connector subclasses Source and implements _search(). search() never raises, and all HTTP goes
through request_json(), so tests mock one function: brandpilot.sources.base.send.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Literal, Optional

import requests
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger("brandpilot.sources")

HEX = r"^#[0-9A-Fa-f]{6}$"
USER_AGENT = "BrandPilot/0.1 (https://github.com/Ashmit-rai17/brandpilot)"
MAX_RETRY_WAIT = 2.0  # seconds; research has an 8 s total budget, so a longer Retry-After means give up

ReferenceType = Literal["inspiration", "asset"]
Verification = Literal["observed", "unverified"]


class ColorShare(BaseModel):
    hex: str = Field(pattern=HEX)
    share: float = Field(ge=0, le=1)  # fraction of preview pixels


class Observed(BaseModel):
    """Computed by BrandPilot from a downloaded preview image. Never filled from text."""
    palette: list[ColorShare] = Field(max_length=8)
    lightness: float = Field(ge=0, le=1)       # mean HSL lightness
    saturation: float = Field(ge=0, le=1)      # mean HSL saturation
    negative_space: float = Field(ge=0, le=1)  # share of low-detail pixels


class Interpreted(BaseModel):
    """Read from the source's text (title, snippet, tags). Unverified by definition."""
    basis: Literal["text"] = "text"
    snippet: str = Field(default="", max_length=400)
    keywords: list[str] = Field(default_factory=list)


class Reference(BaseModel):
    id: str
    source: str                       # connector name, e.g. "tavily:behance.net", "openverse", "wikimedia"
    title: str
    url: str                          # landing page a person can open
    preview_url: Optional[str] = None
    creator: Optional[str] = None
    licence: Optional[str] = None     # e.g. "CC BY-SA 4.0", "Unsplash License"
    licence_url: Optional[str] = None
    reference_type: ReferenceType
    observed: Optional[Observed] = None
    interpreted: Optional[Interpreted] = None
    verification: Verification = "unverified"
    relevance: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _consistent(self):
        if (self.verification == "observed") != (self.observed is not None):
            raise ValueError("verification is 'observed' exactly when observed features are present")
        if self.reference_type == "asset" and not self.licence:
            raise ValueError("an asset reference must carry a licence")
        return self


def ref_id(source: str, url: str) -> str:
    return f"{source.split(':')[0]}_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}"


def send(method: str, url: str, **kwargs) -> requests.Response:
    """The single HTTP choke point. Tests replace this."""
    return requests.request(method, url, **kwargs)


def sleep(seconds: float) -> None:
    """Patched in tests so Retry-After handling runs instantly."""
    time.sleep(seconds)


def request_json(method: str, url: str, *, timeout: float, headers: Optional[dict] = None,
                 params: Optional[dict] = None, json: Optional[dict] = None) -> Optional[dict]:
    """GET/POST and decode JSON. At most one retry: on a network error, a 5xx, or a 429 whose
    Retry-After is within MAX_RETRY_WAIT. Returns None on any failure; never raises."""
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(2):
        try:
            r = send(method, url, headers=hdrs, params=params, json=json, timeout=timeout)
        except requests.RequestException as e:
            log.info("%s %s failed: %s", method, url, type(e).__name__)
            if attempt == 0:
                continue
            return None
        if r.status_code == 429 and attempt == 0:
            wait = _retry_after(r.headers.get("Retry-After"))
            if wait is None or wait > MAX_RETRY_WAIT:
                log.info("%s rate limited (Retry-After %s); giving up", url, r.headers.get("Retry-After"))
                return None
            sleep(wait)
            continue
        if r.status_code >= 500 and attempt == 0:
            continue
        if not r.ok:
            log.info("%s returned %s", url, r.status_code)
            return None
        try:
            data = r.json()
        except ValueError:
            log.info("%s returned malformed JSON", url)
            return None
        return data if isinstance(data, dict) else None
    return None


def _retry_after(value: Optional[str]) -> Optional[float]:
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None  # HTTP-date form: treat as too long for an interactive budget


class Source:
    """Base for every connector. Subclasses set name/timeout and implement _search()."""
    name = "source"
    timeout = 5.0  # seconds per HTTP request

    def enabled(self) -> bool:
        """False when a required key is missing; the aggregator then skips the source."""
        return True

    def search(self, query: str, limit: int = 6) -> list[Reference]:
        if not self.enabled() or not query.strip() or limit <= 0:
            return []
        try:
            refs = self._search(query.strip(), limit)
        except Exception as e:  # a connector bug must never break directions
            log.warning("%s search crashed: %s", self.name, e)
            return []
        return [r for r in refs if isinstance(r, Reference)][:limit]

    def _search(self, query: str, limit: int) -> list[Reference]:
        raise NotImplementedError
