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
from .brain import Brain
from .kb import direction_from_style, fonts, lock_design_system
from .models import AssetRecord, Brief, DesignSystem, Direction, Patch
from .render import compose, to_png
from .revise import RevisionRejected, apply_patch, diff, palette_contrast_ok, preserved, LABELS

log = logging.getLogger("brandpilot.flow")

BRIEF, DIRECTIONS, REVIEW_DS, ASSETS, REVISE_CONFIRM, DONE = (
    "BRIEF", "DIRECTIONS", "REVIEW_DS", "ASSETS", "REVISE_CONFIRM", "DONE")
RESTART = re.compile(r"^\s*(restart|start over|new brand|reset)\b", re.I)
YES = re.compile(r"^\s*(yes|y|ok|okay|approve|approved|looks good|confirm|go|sure)\b", re.I)
NO = re.compile(r"^\s*(no|cancel|nope|reject|back)\b", re.I)
CONFIRM = re.compile(r"\b(confirm(ed|s)?|approv(e|ed|es|al))\b", re.I)
CANCEL = re.compile(r"\b(cancel(l?ed|s)?|reject(ed|s)?|declin(e|ed|es))\b", re.I)
DONE_RE = re.compile(r"^\s*(done|finish|that's all|thats all|finished)\b", re.I)
SOCIAL = re.compile(r"social|instagram|square post|ig post", re.I)


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
            "pending_ds": None, "assets": {}, "rejected": None}


def handle(session: dict, text: str, svc: Services) -> list[Reply]:
    text = (text or "").strip()
    if not session or RESTART.match(text):
        session.clear()
        session.update(new_session())
        if RESTART.match(text):
            return [Reply("Starting fresh. Tell me about your company, product, audience, and a launch headline.",
                          "form", cards.brief_form(Brief()))]
    stage = session["stage"]
    sel = cards.parse_selection(text)
    try:
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
    dirs = [direction_from_style(d["style_id"], d["rationale"], i + 1) for i, d in enumerate(picked["directions"])]
    s["directions"] = [d.model_dump() for d in dirs]
    s["rejected"] = picked.get("rejected")
    s["stage"] = DIRECTIONS
    lines = [f"Here are two directions for {brief.company}:"]
    for i, d in enumerate(dirs, 1):
        lines.append(f"{i}. {d.name} ({fonts()[d.type.heading]['family']} + {fonts()[d.type.body]['family']}, "
                     f"primary {d.palette.primary}): {d.rationale}")
    if s["rejected"]:
        r = s["rejected"]
        lines.append(f"Ruled out: {r['name']}, because its {r['reason']}.")
    lines.append("Choose one on the card, or reply 1 or 2.")
    return [Reply("\n\n".join(lines), "carousel", cards.directions_carousel(dirs))]


def _on_directions(s, text, sel, svc):
    dirs = [Direction(**d) for d in s["directions"]]
    pick = None
    if sel.get("direction_id"):
        pick = next((d for d in dirs if d.id == sel["direction_id"]), None)
    if pick is None:
        m = re.search(r"\b([12])\b", text)
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
    ds = DesignSystem(**s["ds"])
    if DONE_RE.match(text):
        s["stage"] = DONE
        return [Reply(_launch_kit(ds, s), end_session=True)]
    if re.match(r"^\s*(retry|try again|regenerate)\b", text, re.I):
        asset = next(reversed(s["assets"]), "poster") if s["assets"] else "poster"
        return _make_asset(s, svc, asset, regenerate=True, intro="")
    if SOCIAL.search(text):
        return _make_asset(s, svc, "social_post", regenerate=True, intro="")
    patch = svc.brain.write_patch(text, ds)
    try:
        new = apply_patch(ds, patch)
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
    action = sel.get("action")
    old = DesignSystem(**s["ds"])
    if action == "cancel_patch" or (not action and (NO.match(text) or CANCEL.search(text))):
        s["pending_ds"], s["stage"] = None, ASSETS
        return [Reply(f"Cancelled. Design system stays at v{old.version}.")]
    if action == "approve_patch" or YES.match(text) or (not action and CONFIRM.search(text)):
        new = DesignSystem(**s["pending_ds"])
        changes = diff(old, new)
        changed_keys = {k for k, _, _ in changes}
        log.info("revision v%s -> v%s changed=%s", old.version, new.version, changes)
        s["ds"], s["pending_ds"], s["stage"] = new.model_dump(), None, ASSETS
        # Color vibrancy and spacing changes reuse the same background, so composition is preserved.
        regenerate = bool(changed_keys & {"image_style"}) or (
            bool(changed_keys & {"palette.primary", "palette.accent"}) and "saturation" not in changed_keys)
        asset = "poster" if "poster" in s["assets"] else next(iter(s["assets"]), "poster")
        kept = [LABELS.get(k, k) for k in ("type.heading", "type.body", "type.scale", "spacing",
                                          "palette.text", "palette.background", "image_style")
                if k not in changed_keys]
        intro = (f"v{new.version} approved. Changed: {', '.join(LABELS.get(k, k) for k in sorted(changed_keys))}. "
                 f"Preserved: {', '.join(kept)}. "
                 + ("Same background, recolored. " if not regenerate else "New background for the new image style. "))
        return _make_asset(s, svc, asset, regenerate=regenerate, intro=intro)
    return [Reply("Approve or cancel the proposed change.")]


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
    msg = (f"{intro}{label} built from design system v{ds.version}. Design check: {passed}/{len(checks)} passed.\n\n"
           f"{check_lines}\n\nNext: ask for a revision (for example 'make the colors more vibrant'), "
           "say 'social post' for a matching square post, or say 'done' for your launch kit.")
    return [Reply(msg, image_png=png, image_name=out.name)]


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
