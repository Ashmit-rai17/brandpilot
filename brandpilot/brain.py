"""Reasoning steps. ASI1 proposes, pydantic validates, code decides. Each step has a deterministic fallback."""
from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, ValidationError

from . import asi1
from .kb import candidate_styles, styles, vocabulary
from .models import Brief, DesignSystem, Patch

log = logging.getLogger("brandpilot.brain")


class Brain:
    """Real ASI1-backed reasoning. Set offline=True to use only the deterministic fallbacks."""

    def __init__(self, offline: bool = False):
        self.offline = offline
        self.last_source = ""

    # ---------- brief ----------
    def extract_brief(self, text: str, current: Brief) -> Brief:
        vocab = vocabulary()
        system = (
            "You extract a startup brand brief from the founder's message. Return JSON with keys: "
            "company, product, audience, industry, positioning, personality (list), avoid (list), headline. "
            f"industry must be one of {vocab['industry']} or null. "
            f"personality items must come from {vocab['personality']}. positioning is one short word like premium, "
            "affordable, playful, trustworthy. headline is a short launch headline (max 6 words) if the founder gave "
            "one, otherwise write one in their voice. Use null for anything not stated or clearly implied. "
            "Never invent a company name."
        )
        user = json.dumps({"current_brief": current.model_dump(), "founder_message": text})
        if not self.offline:
            try:
                data = asi1.chat_json(system, user)
                merged = current.model_dump()
                for k, v in data.items():
                    if k in merged and v not in (None, "", []):
                        merged[k] = v
                merged["personality"] = [p for p in merged.get("personality", []) if p in vocab["personality"]][:4]
                if merged.get("industry") not in vocab["industry"]:
                    merged["industry"] = current.industry
                self.last_source = "asi1"
                return Brief(**merged)
            except (asi1.ASI1Error, ValueError, ValidationError, TypeError) as e:
                log.warning("extract_brief fallback: %s", e)
        self.last_source = "rules"
        return _rule_brief(text, current)

    # ---------- directions ----------
    def choose_directions(self, brief: Brief) -> dict:
        kept, rejected = candidate_styles(brief)
        pool = kept if len(kept) >= 2 else kept + [s for s, _ in rejected][: 2 - len(kept)]
        ids = [s["id"] for s in pool]
        if not self.offline:
            system = (
                "You are a brand design director. Pick exactly TWO clearly different visual styles for this brief "
                "from the allowed list only, and explain each in one sentence that cites the brief. Return JSON: "
                '{"directions":[{"style_id":"...","rationale":"..."},{"style_id":"...","rationale":"..."}]}'
            )
            user = json.dumps({"brief": brief.model_dump(),
                               "allowed_styles": [{"id": s["id"], "name": s["name"], "summary": s["summary"],
                                                   "use_when": s["use_when"]} for s in pool]})
            try:
                data = asi1.chat_json(system, user)
                picks = [d for d in data.get("directions", []) if d.get("style_id") in ids]
                uniq = list({d["style_id"]: d for d in picks}.values())[:2]
                if len(uniq) == 2:
                    self.last_source = "asi1"
                    return {"directions": uniq, "rejected": _rejection(rejected)}
                log.warning("choose_directions: invalid ids %s", data)
            except (asi1.ASI1Error, ValueError, TypeError, AttributeError) as e:
                log.warning("choose_directions fallback: %s", e)
        self.last_source = "rules"
        tags = brief.tags()
        picks = []
        for s in pool[:2]:
            hits = sorted(tags & set(s["use_when"]))
            why = f"matches {', '.join(hits)}" if hits else "a contrasting option to compare against"
            picks.append({"style_id": s["id"], "rationale": f"{s['summary']} Chosen because it {why}."})
        return {"directions": picks, "rejected": _rejection(rejected)}

    # ---------- revision ----------
    def write_patch(self, request: str, ds: DesignSystem) -> Patch:
        if not self.offline:
            system = (
                "Convert a design revision request into a JSON patch. Allowed keys only: "
                'saturation ("muted"|"balanced"|"vibrant"), temperature ("warmer"|"cooler"), '
                'spacing ("low"|"medium"|"high"), image_style (short phrase), wants_font_change (bool), '
                "reason (short). Include ONLY keys the request asks about. Never change anything else. "
                "If the user asks to change fonts or typography, set wants_font_change true."
            )
            user = json.dumps({"request": request, "current": {"saturation": ds.saturation, "spacing": ds.spacing,
                                                                "image_style": ds.image_style}})
            try:
                data = asi1.chat_json(system, user)
                patch = Patch(**{k: v for k, v in data.items() if k in Patch.model_fields})
                if not patch.is_empty() or patch.wants_font_change:
                    self.last_source = "asi1"
                    return patch
            except (asi1.ASI1Error, ValueError, ValidationError, TypeError) as e:
                log.warning("write_patch fallback: %s", e)
        self.last_source = "rules"
        return rule_patch(request, ds)


def _rejection(rejected) -> dict | None:
    if not rejected:
        return None
    s, clash = rejected[0]
    return {"style_id": s["id"], "name": s["name"], "reason": f"avoid_when matches {', '.join(clash)}"}


# ---------- deterministic fallbacks ----------

def rule_patch(request: str, ds: DesignSystem) -> Patch:
    t = request.lower()
    p = {}
    if re.search(r"vibrant|punch|saturat|bolder colou?r|brighter|pop|more colou?r", t):
        p["saturation"] = "vibrant" if ds.saturation != "vibrant" else None
    elif re.search(r"muted|calmer colou?r|soft(er)? colou?r|desaturat|toned down|subtle", t):
        p["saturation"] = "muted" if ds.saturation != "muted" else None
    if re.search(r"warm", t):
        p["temperature"] = "warmer"
    elif re.search(r"cool|colder", t):
        p["temperature"] = "cooler"
    if re.search(r"more (white ?)?space|breath|airier|roomier|less cramped", t):
        p["spacing"] = {"low": "medium", "medium": "high", "high": "high"}[ds.spacing]
    elif re.search(r"tighter|denser|less space", t):
        p["spacing"] = {"high": "medium", "medium": "low", "low": "low"}[ds.spacing]
    m = re.search(r"\b(?:image|imagery|background|illustration)s?\b.*?\b(?:to|into)\s+something\s+(?:more\s+)?(.+)", t)
    if m:
        p["image_style"] = m.group(1).strip(" .!")
    font = bool(re.search(r"font|typeface|typography|serif", t)) and not re.search(r"keep (the )?(font|type)", t)
    return Patch(**{k: v for k, v in p.items() if v}, wants_font_change=font, reason="keyword rules")


# "I'm launching Forge, an AI tool for developers" / "We're Lumen, a budgeting app for students".
# The name must be capitalised so "I'm launching an AI tool" never becomes a company.
_INTRO = re.compile(r"(?i:\b(?:i'm|i am|we're|we are)(?:\s+(?:launching|building|starting))?)\s+"
                    r"([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*)\s*,\s*(?i:an?)\s+([^.,]+?)\s+for\s+([^.,]+)")
_HEADLINE = re.compile(r"(?i)\bheadline\s*:\s*(.+?)\s*$")
_INDUSTRY = {"dev-tools": r"developer|engineer|\bdevs?\b|\bapi\b|\bsdk\b", "fintech": r"budget|bank|payment|financ"}
_POSITIONING = ("premium", "affordable", "playful", "trustworthy")


def _rule_brief(text: str, current: Brief) -> Brief:
    """Minimal fallback: one-sentence intro, 'Headline: ...', vocabulary words, and 'key: value' lines.
    The form card is the reliable path offline."""
    data = current.model_dump()
    head = _HEADLINE.search(text)
    if head:
        data["headline"] = head.group(1).rstrip(".")
        text = text[: head.start()] + "\n" + text[head.end():]
    intro = _INTRO.search(text)
    if intro:
        data["company"], data["product"], data["audience"] = (g.strip() for g in intro.groups())
    words = re.findall(r"[a-z]+", re.sub(r"(?im)^\s*avoid\s*:.*$", "", text).lower())  # 'avoid:' isn't personality
    found = list(dict.fromkeys(w for w in words if w in vocabulary()["personality"]))
    if found:
        data["personality"] = found[:4]
    data["positioning"] = next((w for w in _POSITIONING if w in words), data["positioning"])
    data["industry"] = next((k for k, p in _INDUSTRY.items() if re.search(p, text, re.I)), data["industry"])
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower()
            if k in data and v.strip():
                data[k] = [x.strip() for x in v.split(",")] if isinstance(data[k], list) else v.strip()
    return Brief(**data)
