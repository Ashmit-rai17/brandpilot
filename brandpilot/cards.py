"""ASI:One Interactive Card payloads (card_protocol_version "1").

Shapes follow innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards.
If ASI:One rejects a payload it falls back to showing the TextContent, so every card message
also carries a plain-text version of the same choice.
"""
from __future__ import annotations

import json
import re

from .models import Brief, DesignSystem, Direction
from .kb import fonts
from .revise import LABELS

BRIEF_FIELDS = {
    "company": ("text", "Company name"),
    "product": ("text", "What the product does, in one line"),
    "audience": ("text", "Who it is for"),
    "headline": ("text", "Launch headline (max 6 words)"),
}


def brief_form(brief: Brief) -> dict:
    fields = [{"name": n, "kind": BRIEF_FIELDS[n][0], "label": BRIEF_FIELDS[n][1], "required": True}
              for n in brief.missing()]
    fields.append({"name": "personality", "kind": "text", "label": "Brand personality, 2 to 3 words", "required": False})
    return {"title": "Tell me about your brand", "fields": fields,
            "submit_cta": {"label": "Continue", "selection": {"action": "submit_brief"}}}


def directions_carousel(dirs: list[Direction]) -> dict:
    items = []
    for d in dirs:
        items.append({
            "id": d.id,
            "title": d.name,
            "subtitle": f"{fonts()[d.type.heading]['family']} + {fonts()[d.type.body]['family']}",
            "badges": [{"label": d.palette.primary, "variant": "info"}],
            "secondary_text": d.rationale[:140],
            "primary_cta": {"label": "Choose", "selection": {"action": "pick_direction", "direction_id": d.id}},
        })
    return {"title": "Two visual directions", "subtitle": "Pick one to build your design system", "items": items}


def ds_review(ds: DesignSystem, title: str = "Approve your design system") -> dict:
    p = ds.palette
    rows = [
        {"label": "Style", "value": ds.style_name},
        {"label": "Palette", "value": f"bg {p.background}, text {p.text}, primary {p.primary}, accent {p.accent}"},
        {"label": "Typography", "value": f"{fonts()[ds.type.heading]['family']} / {fonts()[ds.type.body]['family']}, scale {ds.type.scale}"},
        {"label": "Spacing", "value": ds.spacing},
        {"label": "Imagery", "value": ds.image_style[:90]},
        {"label": "Locked", "value": ", ".join(ds.locked)},
        {"label": "Version", "value": f"v{ds.version}"},
    ]
    return {"title": title, "summary_rows": rows,
            "approve_cta": {"label": "Approve and make poster", "selection": {"action": "approve_ds"}, "primary": True},
            "reject_cta": {"label": "Pick the other direction", "selection": {"action": "reject_ds"}}}


def revision_review(old: DesignSystem, new: DesignSystem, changes, kept_keys) -> dict:
    rows = [{"label": f"{LABELS.get(k, k)} (changed)", "value": f"{a} to {b}"} for k, a, b in changes]
    rows.append({"label": "Typography (preserved)",
                 "value": f"{fonts()[old.type.heading]['family']} / {fonts()[old.type.body]['family']}"})
    for k in ("spacing", "palette.text", "palette.background", "image_style"):
        if k in kept_keys and k not in {c[0] for c in changes}:
            rows.append({"label": f"{LABELS.get(k, k)} (preserved)", "value": str(_get(old, k))[:60]})
    return {"title": f"Proposed change: v{old.version} to v{new.version}", "summary_rows": rows,
            "approve_cta": {"label": "Approve and regenerate", "selection": {"action": "approve_patch"}, "primary": True},
            "reject_cta": {"label": "Cancel", "selection": {"action": "cancel_patch"}}}


def _get(ds, dotted):
    obj = ds
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


# ---------- incoming selections ----------

def parse_selection(text: str) -> dict:
    """Direct @mention sends selection JSON; planner-routed chats send prose. Try JSON first."""
    t = (text or "").strip()
    try:
        data = json.loads(t)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    m = re.search(r"\{.*\}", t, flags=re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    low = t.lower()
    sel: dict = {}
    m = re.search(r"dir[_ ]?(\d)", low)
    if m:
        sel = {"action": "pick_direction", "direction_id": f"dir_{m.group(1)}"}
    for action in ("approve_ds", "reject_ds", "approve_patch", "cancel_patch", "submit_brief", "pick_direction"):
        if action in low or action.replace("_", " ") in low:
            sel.setdefault("action", action)
    return sel
