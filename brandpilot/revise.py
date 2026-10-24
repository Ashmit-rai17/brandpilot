"""Controlled revisions. The LLM proposes a Patch; only this code changes a DesignSystem."""
from __future__ import annotations

from .kb import contrast, set_saturation, shift_temperature, styles
from .models import DesignSystem, Patch
from .variation import generate_palette, hue_for_family, pick_hue_family, pick_layout_template, pick_motif, stable_seed

ALLOWED = {"saturation", "temperature", "spacing", "image_style", "variation"}
# Which design-system fields each patch key may touch. Everything else must stay identical.
TOUCHES = {
    "saturation": {"saturation", "palette.primary", "palette.accent"},
    "temperature": {"palette.primary", "palette.accent"},
    "spacing": {"spacing"},
    "image_style": {"image_style"},
    "variation": {"seed", "variant", "palette.background", "palette.surface", "palette.text", "palette.primary",
                  "palette.accent", "layout_template", "motif.subject", "motif.composition", "motif.lighting",
                  "motif.industry_hint", "hue_family"},
}
LOCK_OF = {"saturation": "palette", "temperature": "palette", "spacing": "spacing", "image_style": "image_style", "variation": ""}


class RevisionRejected(Exception):
    pass


def apply_patch(ds: DesignSystem, patch: Patch, company: str | None = None, industry: str | None = None) -> DesignSystem:
    if patch.wants_font_change and "type" in ds.locked:
        raise RevisionRejected("Typography is locked in this design system, so I kept the fonts as they are.")
    if patch.is_empty():
        raise RevisionRejected("I couldn't map that request to a change I'm allowed to make. "
                               "I can change color vibrancy, warmth, spacing or image feel.")
    for key in ALLOWED:
        if getattr(patch, key) is not None and LOCK_OF[key] and LOCK_OF[key] in ds.locked:
            raise RevisionRejected(f"{LOCK_OF[key].replace('_', ' ').title()} is locked.")

    new = ds.model_copy(deep=True)
    pal = new.palette
    if patch.saturation and patch.saturation != ds.saturation:
        pal.primary = set_saturation(ds.palette.primary, ds.saturation, patch.saturation)
        pal.accent = set_saturation(ds.palette.accent, ds.saturation, patch.saturation)
        new.saturation = patch.saturation
    if patch.temperature:
        pal.primary = shift_temperature(pal.primary, patch.temperature)
        pal.accent = shift_temperature(pal.accent, patch.temperature)
    if patch.spacing:
        new.spacing = patch.spacing
    if patch.image_style:
        new.image_style = patch.image_style
    if patch.variation:
        grammar = styles()[ds.style_id]["grammar"]
        new.variant = ds.variant + 1
        # The live flow supplies the company; the fallback retains deterministic behaviour for old direct callers.
        seed_company = company if company is not None else str(ds.seed or "")
        new.seed = stable_seed(seed_company, ds.style_id, new.variant)
        new.hue_family = pick_hue_family(grammar["palette"]["hue_families"], new.seed)
        new.palette = generate_palette(grammar, hue_for_family(new.hue_family, new.seed), new.seed)
        new.layout_template = pick_layout_template(grammar, new.seed)["id"]
        new.motif = pick_motif(grammar, industry, new.seed)

    new.version = ds.version + 1
    changes = diff(ds, new)
    if not changes:
        raise RevisionRejected("That's already how the design system is set, so nothing would change.")
    new.history = ds.history + [{"from": ds.version, "to": new.version,
                                 "patch": patch.model_dump(exclude_none=True, exclude_defaults=True, exclude={"wants_font_change"}),
                                 "changed": [c[0] for c in changes]}]
    _assert_preserved(ds, new, patch)
    return new


def _flat(ds: DesignSystem) -> dict:
    d = ds.model_dump(exclude={"version", "history"})
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out


def diff(old: DesignSystem, new: DesignSystem) -> list[tuple[str, object, object]]:
    a, b = _flat(old), _flat(new)
    return [(k, a[k], b[k]) for k in a if a[k] != b[k]]


def preserved(old: DesignSystem, new: DesignSystem) -> list[str]:
    a, b = _flat(old), _flat(new)
    return [k for k in a if a[k] == b[k]]


def _assert_preserved(old: DesignSystem, new: DesignSystem, patch: Patch) -> None:
    allowed = set().union(*(TOUCHES[k] for k in ALLOWED if getattr(patch, k) is not None))
    illegal = [k for k, _, _ in diff(old, new) if k not in allowed]
    if illegal:
        raise RevisionRejected(f"Internal guard: patch tried to change {illegal}")


def palette_contrast_ok(ds: DesignSystem) -> float:
    return contrast(ds.palette.text, ds.palette.background)


LABELS = {
    "saturation": "Color vibrancy", "palette.primary": "Primary color", "palette.accent": "Accent color",
    "spacing": "Spacing", "image_style": "Image style", "type.heading": "Heading font",
    "type.body": "Body font", "type.scale": "Type scale", "palette.text": "Text color",
    "palette.background": "Background color", "style_id": "Style",
    "seed": "Variation seed", "variant": "Variation", "layout_template": "Layout template",
    "motif": "Image motif", "hue_family": "Hue family",
}
