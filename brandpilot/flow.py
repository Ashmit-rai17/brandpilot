"""BrandPilot conversation state machine.

handle(session, text, services) -> list[Reply]. No uAgents imports here, so the whole
workflow runs in tests and in the terminal simulator exactly as it runs in ASI:One.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import cards
from .asi1 import compile_prompt
from .brain import Brain, rule_patch
from .kb import direction_from_style, fonts, lock_design_system, styles
from .models import AssetRecord, Brief, DesignSystem, Direction, Patch
from .render import compose, to_png
from .revise import RevisionRejected, apply_patch, diff, palette_contrast_ok, preserved, LABELS

log = logging.getLogger("brandpilot.flow")

BRIEF, DIRECTIONS, REVIEW_DS, ASSETS, REVISE_CONFIRM, DONE = (
    "BRIEF", "DIRECTIONS", "REVIEW_DS", "ASSETS", "REVISE_CONFIRM", "DONE")
RESTART = re.compile(r"^\s*(restart|start over|new brand|reset)\b", re.I)
RESTART_ANY = re.compile(r"\b(restart|start over)\b", re.I)  # "please restart" / "can we start over?"
RETRY = re.compile(r"^\s*(retry|try again|regenerate)\b", re.I)
YES = re.compile(r"^\s*(yes|y|ok|okay|approve|approved|looks good|confirm|go|sure)\b", re.I)
NO = re.compile(r"^\s*(no|cancel|nope|reject|back)\b", re.I)
CONFIRM = re.compile(r"\b(confirm(ed|s)?|approv(e|ed|es|al))\b", re.I)
CANCEL = re.compile(r"\b(cancel(l?ed|s)?|reject(ed|s)?|declin(e|ed|es))\b", re.I)
DONE_RE = re.compile(r"^\s*(done|finish|that's all|thats all|finished)\b", re.I)
SOCIAL = re.compile(r"social|instagram|square post|ig post", re.I)
STALE_ACTIONS = {"approve_ds", "reject_ds", "pick_direction", "submit_brief", "approve_patch", "cancel_patch"}
EARLIER_CARD = re.compile(r"design system|direction", re.I)
MENTION = re.compile(r"^\s*@\S+\s*")  # ASI:One direct mentions arrive as "@brandpilot ..." or "@agent1q... ..."
# "I'm launching Forge, ..." / "We're Lumen, a ..." / "... Headline: ..." looks like a brand-new brief
NEW_BRIEF = re.compile(r"^\s*(?i:i'?m|i am|we'?re|we are)\s+(?:(?i:launching|building|starting)\b|[A-Z][\w&.-]*\s*,)"
                       r"|(?i:\b(?:headline|brand name|company|product|audience)\s*:)")
NEW_BRAND_REPLY = "Looks like a new brand. Say 'restart' to start fresh, or ask for a revision to the current poster."
# Universal intents. Greetings/thanks count only when nothing else is left once their words are removed,
# so "hi, make the colors more vibrant" is still a revision.
GREETING = re.compile(r"\b(hi|hello|hey|yo|good (morning|afternoon|evening))\b", re.I)
THANKS = re.compile(r"\b(thanks|thank you|thx|great|nice|cool)\b", re.I)
FILLER = re.compile(r"\b(there|again|so|much|very|a lot|all|brandpilot)\b", re.I)
HELP = re.compile(r"^(what can you do|what do you do|help|how does (this|it) work|who are you)( for me)?[\s?.!]*$", re.I)
STATUS = re.compile(r"^(status|where are we|what'?s next|what now)[\s?.!]*$", re.I)
ACCEPT = re.compile(r"^(yes|sure|ok|okay|do it)( please)?[\s.!]*$", re.I)
NUMBER = re.compile(r"^([1-3])[\s.!]*$")
SUGGESTABLE = {"saturation", "temperature", "spacing"}  # the only Patch keys a suggestion may carry
STAGE_LABEL = {BRIEF: "Brief", DIRECTIONS: "Directions", REVIEW_DS: "Design system review", ASSETS: "Assets",
               REVISE_CONFIRM: "Revision review", DONE: "Done"}


@dataclass
class Reply:
    text: str
    card_kind: Optional[str] = None
    card_payload: Optional[dict] = None
    image_png: Optional[bytes] = None
    image_name: str = ""
    end_session: bool = False


@dataclass
class Services:
    brain: Brain
    generate_image: Callable[[str], bytes]
    data_dir: Path = field(default_factory=lambda: Path("data"))


def new_session() -> dict:
    return {"stage": BRIEF, "brief": Brief().model_dump(), "directions": [], "ds": None,
            "pending_ds": None, "assets": {}, "rejected": None, "suggestions": []}


def is_restart(text: str) -> bool:
    """'restart' at the start, or 'restart'/'start over' anywhere in a short message (under 25 words)."""
    if RESTART.match(text):
        return True
    if len(text.split()) < 25 and RESTART_ANY.search(text):
        log.info("restart detected inside message: %r", text[:80])
        return True
    return False


def is_long_action(session: dict, text: str) -> bool:
    """True when handling this message may generate an image (approve, approve revision, social post, retry)."""
    text = MENTION.sub("", (text or "").strip())
    stage, sel = session.get("stage"), cards.parse_selection(text)
    action = sel.get("action")
    if action:
        if action == "apply_suggestion":
            pick = next((x for x in session.get("suggestions") or [] if x["id"] == sel.get("suggestion_id")), None)
            return bool(pick and pick["kind"] == "social_post")
        return (stage, action) in {(REVIEW_DS, "approve_ds"), (REVISE_CONFIRM, "approve_patch")}
    agrees = (YES.match(text) or CONFIRM.search(text)) and not (NO.match(text) or CANCEL.search(text))
    if stage in (REVIEW_DS, REVISE_CONFIRM):
        return bool(agrees)
    if stage == ASSETS:
        pending = session.get("suggestions") or []
        n = NUMBER.match(text)
        pick = pending[int(n.group(1)) - 1] if n and int(n.group(1)) <= len(pending) else (
            pending[0] if len(pending) == 1 and ACCEPT.match(text) else None)
        return bool(SOCIAL.search(text) or RETRY.match(text) or (pick and pick["kind"] == "social_post"))
    return False


def handle(session: dict, text: str, svc: Services) -> list[Reply]:
    text = MENTION.sub("", (text or "").strip())
    restart = is_restart(text)
    if not session or restart:
        session.clear()
        session.update(new_session())
        if restart:
            return [Reply("Starting fresh. Tell me about your company, product, audience, and a launch headline.",
                          "form", cards.brief_form(Brief()))]
    stage = session["stage"]
    sel = cards.parse_selection(text)
    try:
        intent = None if sel else _intent(text)
        if intent == "greeting" and stage == BRIEF and session["brief"] == Brief().model_dump():
            return _on_brief(session, "hi", {}, svc)  # first contact keeps the intro + form
        if intent:
            return [_intent_reply(session, intent)]
        replies = _on_suggestion(session, text, sel, svc)
        if replies:
            return replies
        session["suggestions"] = []  # any other message drops pending suggestions
        if stage == BRIEF:
            return _on_brief(session, text, sel, svc)
        if stage == DIRECTIONS:
            return _on_directions(session, text, sel, svc)
        if stage == REVIEW_DS:
            return _on_review_ds(session, text, sel, svc)
        if stage == ASSETS:
            return _on_assets(session, text, sel, svc)
        if stage == REVISE_CONFIRM:
            return _on_revise_confirm(session, text, sel, svc)
        return [Reply("This session is complete. Say 'restart' to design a new brand.")]
    except Exception as e:  # never corrupt state; tell the user what happened
        log.exception("flow error")
        return [Reply(f"Something went wrong on my side ({type(e).__name__}). Your progress is saved; "
                      f"send the same message again to retry.")]


# ---------- stages ----------

def _on_brief(s, text, sel, svc):
    brief = Brief(**s["brief"])
    if sel.get("action") == "submit_brief" or (sel and set(sel) & set(cards.BRIEF_FIELDS)):
        data = brief.model_dump()
        for k in ("company", "product", "audience", "headline"):
            if sel.get(k):
                data[k] = str(sel[k]).strip()
        if sel.get("personality"):
            data["personality"] = [p.strip().lower() for p in str(sel["personality"]).split(",") if p.strip()]
        brief = Brief(**data)
        # Let ASI1 classify industry/positioning from the filled form. A prose forward of a form
        # submit carries no field keys, so parse the user's text instead of discarding it.
        has_fields = bool(set(sel) & set(cards.BRIEF_FIELDS))
        brief = svc.brain.extract_brief(_brief_as_text(brief) if has_fields else text, brief)
    elif text and text.lower() not in {"hi", "hello", "hey", "start"}:
        brief = svc.brain.extract_brief(text, brief)
    s["brief"] = brief.model_dump()
    missing = brief.missing()
    if missing:
        intro = "Hi, I'm BrandPilot. " if not text or text.lower() in {"hi", "hello", "hey", "start"} else ""
        return [Reply(f"{intro}I need a bit more before I can propose directions: {', '.join(missing)}. "
                      "Fill in the form, or just type it.", "form", cards.brief_form(brief))]
    return _propose_directions(s, brief, svc)


def _propose_directions(s, brief, svc):
    picked = svc.brain.choose_directions(brief)
    dirs = [direction_from_style(d["style_id"], d["rationale"], i + 1, company=brief.company,
                                 industry=brief.industry, hue_family=d.get("hue_family"))
            for i, d in enumerate(picked["directions"])]
    s["directions"] = [d.model_dump() for d in dirs]
    s["rejected"] = picked.get("rejected")
    s["stage"] = DIRECTIONS
    lines = [f"Here are two directions for {brief.company}:"]
    for i, d in enumerate(dirs, 1):
        source = picked["directions"][i - 1]
        lines.append(f"{i}. {d.name} ({fonts()[d.type.heading]['family']} + {fonts()[d.type.body]['family']}, "
                     f"primary {d.palette.primary}): {d.rationale} Hue: {d.hue_family} — {source.get('hue_reason', '')}")
    if s["rejected"]:
        r = s["rejected"]
        lines.append(f"Ruled out: {r['name']}, because its {r['reason']}.")
    lines.append("Choose one on the card, or reply 1 or 2.")
    tags = brief.tags()  # the same brief tags candidate_styles ranks styles by
    hits = [sorted(tags & set(styles()[d.style_id]["use_when"])) for d in dirs]
    best = max(range(len(dirs)), key=lambda i: len(hits[i]))  # ties keep the first direction
    rec, h = dirs[best], hits[best]
    why = f"it matches {_and(h)} from your brief" if h else "it is the closer fit to your brief"
    lines.append(f"I'd go with {rec.name}: {why}. Say yes to use {rec.name}, or pick the other one.")
    s["suggestions"] = [{"id": f"sug_{rec.id}", "label": f"Use {rec.name}", "kind": "pick_direction",
                         "payload": {"direction_id": rec.id}}]
    return [Reply("\n\n".join(lines), "carousel", cards.directions_carousel(dirs))]


def _on_directions(s, text, sel, svc):
    dirs = [Direction(**d) for d in s["directions"]]
    pick = None
    if sel.get("direction_id"):
        pick = next((d for d in dirs if d.id == sel["direction_id"]), None)
    if pick is None:
        bare = re.sub(r"^\s*@\S+\s*", "", text).strip()  # drop the "@agent1q..." mention prefix
        m = re.search(r"\b(?:option|dir(?:ection)?)\s*([12])\b", text, re.I) or (
            re.search(r"\b([12])\b", bare) if len(bare) <= 20 else None)
        if m:
            pick = dirs[int(m.group(1)) - 1]
        else:
            low = text.lower()
            pick = next((d for d in dirs if d.name.lower() in low or d.style_id.replace("_", " ") in low), None)
    if pick is None:
        return [Reply("Which direction should I use? Reply 1 or 2.", "carousel", cards.directions_carousel(dirs))]
    ds = lock_design_system(pick)
    s["ds"] = ds.model_dump()
    s["stage"] = REVIEW_DS
    c = palette_contrast_ok(ds)
    return [Reply(
        f"Design system v{ds.version} for {pick.name}. Text on background contrast is {c:.1f}:1 "
        f"({'passes' if c >= 4.5 else 'fails'} WCAG AA 4.5:1). Typography is locked so every asset uses the same "
        "fonts. Approve it and I'll make the poster.", "review", cards.ds_review(ds))]


def _on_review_ds(s, text, sel, svc):
    action = sel.get("action")
    if action == "pick_direction" and any(d["id"] == sel.get("direction_id") for d in s["directions"]):
        s["stage"] = DIRECTIONS
        return _on_directions(s, text, sel, svc)
    if action == "reject_ds" or (not action and (NO.match(text) or CANCEL.search(text))):
        s["stage"] = DIRECTIONS
        dirs = [Direction(**d) for d in s["directions"]]
        return [Reply("No problem. Pick the other direction.", "carousel", cards.directions_carousel(dirs))]
    if action == "approve_ds" or YES.match(text) or (not action and CONFIRM.search(text)):
        s["stage"] = ASSETS
        return _make_asset(s, svc, "poster", regenerate=True, intro="Design system approved. ")
    ds = DesignSystem(**s["ds"])
    return [Reply("Approve this design system, or pick the other direction.", "review", cards.ds_review(ds))]


def _on_assets(s, text, sel, svc):
    if not sel and NEW_BRIEF.search(text):
        return [Reply(NEW_BRAND_REPLY)]
    ds = DesignSystem(**s["ds"])
    stale_prose = not sel and EARLIER_CARD.search(text) and (CONFIRM.search(text) or CANCEL.search(text))
    if stale_prose:
        wish = rule_patch(text, ds)  # a real revision request riding along with approval words still counts
        stale_prose = wish.is_empty() and not wish.wants_font_change
    if sel.get("action") in STALE_ACTIONS or stale_prose:
        return [Reply(f"That's already done: your poster uses design system v{ds.version}. "
                      "Ask for a revision, say 'social post', or 'done'.")]
    if DONE_RE.match(text):
        return _finish(s, ds)
    if RETRY.match(text):
        asset = next(reversed(s["assets"]), "poster") if s["assets"] else "poster"
        return _make_asset(s, svc, asset, regenerate=True, intro="")
    if SOCIAL.search(text):
        return _make_asset(s, svc, "social_post", regenerate=True, intro="")
    patch = svc.brain.write_patch(text, ds)
    if patch.is_empty() and not patch.wants_font_change:
        lines, card = _offer(s, ds)
        return [Reply(f"I can help with your brand's design. Try:\n{lines}\n\nReply with a number, "
                      "or ask for another change.", "carousel", card)]
    return _propose(s, ds, patch)


def _propose(s, ds, patch):
    try:
        brief = Brief(**s["brief"])
        new = apply_patch(ds, patch, company=brief.company, industry=brief.industry)
    except RevisionRejected as e:
        return [Reply(f"{e} Try something like 'make the colors more vibrant' or 'more breathing room'.")]
    changes = diff(ds, new)
    s["pending_ds"] = new.model_dump()
    s["pending_patch"] = patch.model_dump()
    s["stage"] = REVISE_CONFIRM
    note = " Fonts stay locked." if patch.wants_font_change else ""
    summary = "; ".join(f"{LABELS.get(k, k)}: {a} to {b}" for k, a, b in changes)
    return [Reply(f"Proposed revision v{ds.version} to v{new.version}: {summary}. Everything else stays the same."
                  f"{note} Approve to regenerate.", "review",
                  cards.revision_review(ds, new, changes, preserved(ds, new)))]


def _on_revise_confirm(s, text, sel, svc):
    if not sel and NEW_BRIEF.search(text):
        return [Reply(NEW_BRAND_REPLY)]
    action = sel.get("action")
    old = DesignSystem(**s["ds"])
    if action in {"approve_ds", "reject_ds", "pick_direction", "submit_brief"} and s.get("pending_ds"):
        new = DesignSystem(**s["pending_ds"])
        return [Reply(f"Approve or cancel the proposed change v{old.version} to v{new.version}.", "review",
                      cards.revision_review(old, new, diff(old, new), preserved(old, new)))]
    if action == "cancel_patch" or (not action and (NO.match(text) or CANCEL.search(text))):
        s["pending_ds"], s["stage"] = None, ASSETS
        if (s.get("pending_patch") or {}).get("reason") == "suggestion":  # keep the list the user was reading
            lines, card = _offer(s, old)
            return [Reply(f"Cancelled. Design system stays at v{old.version}. Other options:\n{lines}",
                          "carousel", card)]
        return [Reply(f"Cancelled. Design system stays at v{old.version}.")]
    if action == "approve_patch" or YES.match(text) or (not action and CONFIRM.search(text)):
        new = DesignSystem(**s["pending_ds"])
        changes = diff(old, new)
        changed_keys = {k for k, _, _ in changes}
        log.info("revision v%s -> v%s changed=%s", old.version, new.version, changes)
        s["ds"], s["pending_ds"], s["stage"] = new.model_dump(), None, ASSETS
        # Color vibrancy and spacing changes reuse the same background, so composition is preserved.
        regenerate = bool(changed_keys & {"image_style", "layout_template", "motif", "seed", "variant", "hue_family"}) or (
            bool(changed_keys & {"palette.primary", "palette.accent"}) and "saturation" not in changed_keys)
        asset = "poster" if "poster" in s["assets"] else next(iter(s["assets"]), "poster")
        kept = [LABELS.get(k, k) for k in ("type.heading", "type.body", "type.scale", "spacing",
                                          "palette.text", "palette.background", "image_style", "seed", "motif", "layout_template")
                if k not in changed_keys]
        intro = (f"v{new.version} approved. Changed: {', '.join(LABELS.get(k, k) for k in sorted(changed_keys))}. "
                 f"Preserved: {', '.join(kept)}. "
                 + ("Same background, recolored. " if not regenerate else "New background for the new image style. "))
        return _make_asset(s, svc, asset, regenerate=regenerate, intro=intro)
    return [Reply("Approve or cancel the proposed change.")]


def _finish(s, ds):
    s["stage"] = DONE
    return [Reply(_launch_kit(ds, s), end_session=True)]


# ---------- suggestions ----------

def _suggestions(ds: DesignSystem, s) -> list[dict]:
    """2-3 deterministic next steps. A design change is offered only if applying it really changes something."""
    cands = [({"saturation": "vibrant"}, "Make the colors more vibrant") if ds.saturation != "vibrant"
             else ({"saturation": "balanced"}, "Tone the colors down to balanced"),
             ({"spacing": "high"}, "Give the layout more breathing room") if ds.spacing != "high"
             else ({"spacing": "medium"}, "Tighten the spacing a little")]
    if not any("temperature" in h.get("patch", {}) for h in ds.history):
        cands.append(({"temperature": "warmer"}, "Warm up the palette"))
    last = ds.history[-1].get("patch", {}) if ds.history else {}
    out = []
    for payload, label in cands:
        if set(payload) & set(last):
            continue  # never offer to undo (or redo) the change the user just approved
        try:
            changed = diff(ds, apply_patch(ds, Patch(**payload)))
        except RevisionRejected:
            changed = []
        if changed and len(out) < 2:
            (key, val), = payload.items()
            out.append({"id": f"sug_v{ds.version}_{key}_{val}", "label": label, "kind": "patch", "payload": payload})
    if "social_post" not in s["assets"]:
        out.append({"id": f"sug_v{ds.version}_social_post", "label": "Make a matching social post",
                    "kind": "social_post", "payload": {}})
    else:
        out.append({"id": f"sug_v{ds.version}_done", "label": "Finish and get your launch kit",
                    "kind": "done", "payload": {}})
    return out


def _offer(s, ds):
    """Store fresh suggestions; return them as a numbered text list (fallback) and a carousel card."""
    s["suggestions"] = _suggestions(ds, s)
    lines = "\n".join(f"{i}. {x['label']}" for i, x in enumerate(s["suggestions"], 1))
    return lines, cards.suggestions_carousel(s["suggestions"])


def _on_suggestion(s, text, sel, svc):
    """Accept a pending suggestion by card click, number (ASSETS only) or "yes". None means not handled here."""
    pending, stage = s.get("suggestions") or [], s["stage"]
    if sel.get("action") == "apply_suggestion":
        pick = next((x for x in pending if x["id"] == sel.get("suggestion_id")), None)
        if pick is None:
            return [Reply(f"That suggestion is no longer available. Next: {_next_step(s)}")]
    elif pending and not sel and stage in (DIRECTIONS, ASSETS):
        n = NUMBER.match(text) if stage == ASSETS else None  # at DIRECTIONS "1"/"2" still mean the direction
        if n and int(n.group(1)) <= len(pending):
            pick = pending[int(n.group(1)) - 1]
        elif ACCEPT.match(text) and len(pending) > 1:
            return [Reply(f"Which one? Reply {_choices(len(pending))}.")]
        elif ACCEPT.match(text):
            pick = pending[0]
        else:  # planner-narrated click: "The user chose 'Make a matching social post'"
            low = text.lower()
            pick = next((x for x in pending if x["label"].lower() in low), None)
            if pick is None:
                return None
    elif stage == ASSETS and not sel and ACCEPT.match(text):
        return [Reply(f"There's nothing waiting for a yes right now. Next: {_next_step(s)}")]
    else:
        return None
    s["suggestions"] = []
    return _apply_suggestion(s, pick, svc)


def _apply_suggestion(s, x, svc):
    kind, payload = x["kind"], x["payload"]
    if kind == "pick_direction":
        return _on_directions(s, "", {"direction_id": payload["direction_id"]}, svc)  # same path as a card click
    ds = DesignSystem(**s["ds"])
    if kind == "patch":
        if set(payload) - SUGGESTABLE:
            raise ValueError(f"suggestion carries unexpected keys {sorted(payload)}")
        return _propose(s, ds, Patch(**payload, reason="suggestion"))  # review card first, never auto-applied
    if kind == "social_post":
        return _make_asset(s, svc, "social_post", regenerate=True, intro="")
    return _finish(s, ds)


# ---------- universal intents ----------

def _intent(text: str) -> Optional[str]:
    if HELP.match(text):
        return "help"
    if STATUS.match(text):
        return "status"
    rest = re.sub(r"\W+", "", FILLER.sub("", THANKS.sub("", GREETING.sub("", text))))
    if len(text.split()) <= 8 and not rest and (GREETING.search(text) or THANKS.search(text)):
        return "greeting" if GREETING.search(text) else "thanks"
    return None


def _intent_reply(s, intent) -> Reply:
    if intent == "help":
        text = ("I'm BrandPilot, your brand design director. I turn a short brief into two visual directions, lock "
                "the one you pick into a design system, then build an on-brand poster and social post. Every "
                "revision is shown for approval first, and fonts stay locked so assets stay consistent. Try: "
                "\"We're Lumen, a budgeting app for students. Headline: Money, made simple.\", "
                "\"make the colors more vibrant\" or \"social post\".\n\n" + _status(s))
    elif intent == "status":
        text = _status(s)
    elif intent == "greeting":
        text = f"Hi! I'm BrandPilot, your brand design director. {_progress(s)} Next: {_next_step(s)}"
    else:
        text = f"You're welcome! {_progress(s)} Next: {_next_step(s)}"
    if s["stage"] == BRIEF:
        return Reply(text, "form", cards.brief_form(Brief(**s["brief"])))
    return Reply(text)


def _status(s) -> str:
    stage, b = s["stage"], Brief(**s["brief"])
    lines = [f"Stage: {STAGE_LABEL[stage]}.", f"Brand: {b.company or 'not set yet'}."]
    if s.get("ds") and stage not in (BRIEF, DIRECTIONS):
        ds = DesignSystem(**s["ds"])
        lines.append(f"Design system: v{ds.version} ({ds.style_name}).")
    lines.append(f"Assets: {_and(_asset_list(s)) or 'none yet'}.")
    lines.append(f"Next: {_next_step(s)}")
    return "\n".join(lines)


def _progress(s) -> str:
    stage, b = s["stage"], Brief(**s["brief"])
    if stage == BRIEF or not b.company:
        return "We're just getting started on your brief."
    v = s["ds"]["version"] if s.get("ds") else 1
    where = {DIRECTIONS: "two directions are ready to compare",
             REVIEW_DS: f"design system v{v} is waiting for your approval",
             REVISE_CONFIRM: f"a revision from v{v} to v{v + 1} is waiting for your approval",
             DONE: "your launch kit is done"}.get(stage)
    if where is None:
        assets = _asset_list(s)
        where = f"your {_and(assets)} {'is' if len(assets) == 1 else 'are'} ready" if assets else "assets come next"
    return f"We're working on {b.company}; {where}."


def _next_step(s) -> str:
    stage = s["stage"]
    if stage == BRIEF:
        return f"tell me your {_and(Brief(**s['brief']).missing())}, or fill in the form."
    if stage == DIRECTIONS:
        return "pick direction 1 or 2" + (", or say yes to use my pick." if s.get("suggestions") else ".")
    v = s["ds"]["version"]
    if stage == REVIEW_DS:
        return f"approve design system v{v}, or pick the other direction."
    if stage == REVISE_CONFIRM:
        return f"approve or cancel the proposed change v{v} to v{v + 1}."
    if stage == DONE:
        return "say 'restart' to design a new brand."
    n = len(s.get("suggestions") or [])
    return (f"reply {_choices(n)} for a suggestion, " if n else "") + "ask for a revision, say 'social post', or 'done'."


def _asset_list(s) -> list[str]:
    return [f"{k.replace('_', ' ')} (v{a['ds_version']})" for k, a in s["assets"].items()]


def _and(items) -> str:
    return " and ".join([", ".join(items[:-1]), items[-1]]) if len(items) > 1 else "".join(items)


def _choices(n) -> str:
    return _and([str(i) for i in range(1, n + 1)]).replace(" and ", " or ")


# ---------- assets ----------

def _make_asset(s, svc, asset_type, regenerate, intro):
    ds = DesignSystem(**s["ds"])
    brief = Brief(**s["brief"])
    sid = s.setdefault("sid", hashlib.sha1((brief.company or "x").encode()).hexdigest()[:8])
    folder = Path(svc.data_dir) / "sessions" / sid
    folder.mkdir(parents=True, exist_ok=True)
    prev = s["assets"].get(asset_type)
    prompt = compile_prompt(ds, asset_type)
    if regenerate or not prev:
        try:
            t = time.time()
            bg = svc.generate_image(prompt)
            log.info("image generated in %.1fs", time.time() - t)
        except Exception as e:
            log.warning("image generation failed: %s", e)
            return [Reply(f"{intro}Image generation failed ({e}). Your design system is saved at v{ds.version}. "
                          "Send 'retry' to try again.")] if not prev else [Reply(
                          f"{intro}Image generation failed, so nothing was changed on the existing asset. Send 'retry'.")]
        bg_path = folder / f"bg_{asset_type}_v{ds.version}.png"
        bg_path.write_bytes(bg)
        bg_sat = ds.saturation
    else:
        bg_path = Path(prev["background_path"])
        bg = bg_path.read_bytes()
        bg_sat = prev["bg_saturation"]
    log.info("asset %s v%s background=%s (%s) primary=%s accent=%s saturation=%s", asset_type, ds.version,
             bg_path, "new" if regenerate or not prev else "reused", ds.palette.primary, ds.palette.accent,
             ds.saturation)
    img, checks, layout = compose(bg, ds, brief, asset_type, bg_saturation=bg_sat)
    png = to_png(img)
    out = folder / f"{asset_type}_v{ds.version}.png"
    out.write_bytes(png)
    rec = AssetRecord(asset_type=asset_type, ds_version=ds.version, prompt=prompt,
                      background_path=str(bg_path), output_path=str(out), checks=checks)
    s["assets"][asset_type] = rec.model_dump() | {"bg_saturation": bg_sat}
    passed = sum(c.passed for c in checks)
    check_lines = "\n".join(f"{'PASS' if c.passed else 'FAIL'}  {c.name}: {c.value} (needs {c.threshold})"
                            for c in checks)
    label = "Poster" if asset_type == "poster" else "Social post"
    lines, card = _offer(s, ds)
    msg = (f"{intro}{label} built from design system v{ds.version}. Design check: {passed}/{len(checks)} passed.\n\n"
           f"{check_lines}\n\nWhat I'd do next:\n{lines}\n\nReply with a number or tap a card, "
           "or ask for any other revision.")
    return [Reply(msg, "carousel", card, image_png=png, image_name=out.name)]


def _launch_kit(ds: DesignSystem, s) -> str:
    p = ds.palette
    h, b = fonts()[ds.type.heading]["family"], fonts()[ds.type.body]["family"]
    css = (f":root {{\n  --bp-bg: {p.background};\n  --bp-surface: {p.surface};\n  --bp-text: {p.text};\n"
           f"  --bp-primary: {p.primary};\n  --bp-accent: {p.accent};\n  --bp-font-heading: '{h}', sans-serif;\n"
           f"  --bp-font-body: '{b}', sans-serif;\n  --bp-type-scale: {ds.type.scale};\n}}")
    assets = ", ".join(f"{k} (v{v['ds_version']})" for k, v in s["assets"].items())
    return (f"Your launch kit, design system v{ds.version} ({ds.style_name}). Assets: {assets}.\n\n"
            f"```css\n{css}\n```\n\nRevision history: {len(ds.history)} approved change(s). Say 'restart' for a new brand.")


def _brief_as_text(b: Brief) -> str:
    return (f"company: {b.company}\nproduct: {b.product}\naudience: {b.audience}\n"
            f"personality: {', '.join(b.personality)}\nheadline: {b.headline}")
