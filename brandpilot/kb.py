"""Knowledge base access plus deterministic color rules."""
from __future__ import annotations

import colorsys
import json
from functools import lru_cache
from pathlib import Path

from .models import Brief, DesignSystem, Direction, Palette, TypeSpec
from .variation import generate_palette, hue_for_family, pick_font_pairing, pick_hue_family, pick_layout_template, pick_motif, stable_seed

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "knowledge"
FONTS = ROOT / "assets" / "fonts"


@lru_cache
def styles() -> dict[str, dict]:
    data = json.loads((KNOWLEDGE / "styles.json").read_text())
    return {s["id"]: s for s in data["styles"]}


@lru_cache
def vocabulary() -> dict[str, list[str]]:
    return json.loads((KNOWLEDGE / "styles.json").read_text())["tag_vocabulary"]


@lru_cache
def fonts() -> dict[str, dict]:
    data = json.loads((KNOWLEDGE / "typography.json").read_text())
    return {f["id"]: f for f in data["fonts"]}


@lru_cache
def margin_ratio() -> dict[str, float]:
    return json.loads((KNOWLEDGE / "typography.json").read_text())["spacing_margin_ratio"]


def font_path(font_id: str) -> Path:
    return FONTS / fonts()[font_id]["file"]


# ---------- style selection ----------

def candidate_styles(brief: Brief) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    """Drop styles whose avoid_when matches the brief. Returns (kept, rejected_with_reasons)."""
    tags = brief.tags() | {a.lower() for a in brief.avoid}
    kept, rejected = [], []
    for s in styles().values():
        clash = sorted(tags & set(s["avoid_when"]))
        # Things the founder explicitly wants to avoid can also be style traits.
        clash += [a for a in brief.avoid if a.lower() in s["summary"].lower()]
        (rejected if clash else kept).append((s, clash) if clash else s)
    kept.sort(key=lambda s: -len(tags & set(s["use_when"])))
    return kept, rejected


def direction_from_style(style_id: str, rationale: str, idx: int, company: str | None = None,
                         industry: str | None = None, variant: int = 0, hue_family: str | None = None) -> Direction:
    s = styles()[style_id]
    grammar = s["grammar"]
    seed = stable_seed(company, style_id, variant)
    family = hue_family if hue_family in grammar["palette"]["hue_families"] else pick_hue_family(grammar["palette"]["hue_families"], seed)
    hue = hue_for_family(family, seed)
    layout = pick_layout_template(grammar, seed)
    return Direction(
        id=f"dir_{idx}", style_id=style_id, name=s["name"], rationale=rationale,
        palette=generate_palette(grammar, hue, seed), type=pick_font_pairing(grammar, seed), seed=seed,
        variant=variant, layout_template=layout["id"], motif=pick_motif(grammar, industry, seed), hue_family=family,
    )


def lock_design_system(d: Direction) -> DesignSystem:
    s = styles()[d.style_id]
    return DesignSystem(
        style_id=d.style_id, style_name=d.name, palette=d.palette, type=d.type,
        spacing=s["spacing"], panel=s["panel"], image_style=s["image_style"],
        prompt_fragment=s["prompt_fragment"], negative=s["negative"],
        seed=d.seed, variant=d.variant, layout_template=d.layout_template, motif=d.motif, hue_family=d.hue_family,
    )


# ---------- color math ----------

def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02X}" for c in rgb)


def rel_luminance_rgb(r: float, g: float, b: float) -> float:
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def luminance(hex_color: str) -> float:
    return rel_luminance_rgb(*_rgb(hex_color))


def contrast_ratio_lum(l1: float, l2: float) -> float:
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def contrast(a: str, b: str) -> float:
    return contrast_ratio_lum(luminance(a), luminance(b))


SAT_FACTOR = {"muted": 0.55, "balanced": 1.0, "vibrant": 1.0}


def set_saturation(hex_color: str, current: str, target: str) -> str:
    """Move a color between saturation levels, keeping hue and value (HSV chroma change)."""
    order = ["muted", "balanced", "vibrant"]
    steps = order.index(target) - order.index(current)
    if steps == 0:
        return hex_color.upper()
    h, s, v = colorsys.rgb_to_hsv(*_rgb(hex_color))
    for _ in range(abs(steps)):
        s = min(1.0, s + (1 - s) * 0.6) if steps > 0 else s * 0.55
    return _hex(colorsys.hsv_to_rgb(h, s, v))


def shift_temperature(hex_color: str, direction: str, degrees: float = 18.0) -> str:
    """Rotate hue toward orange (warmer, 30 deg) or blue (cooler, 215 deg)."""
    h, l, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    target = (30 if direction == "warmer" else 215) / 360
    diff = ((target - h + 0.5) % 1.0) - 0.5
    step = min(abs(diff), degrees / 360) * (1 if diff > 0 else -1)
    return _hex(colorsys.hls_to_rgb((h + step) % 1.0, l, s))
