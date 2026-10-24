"""Deterministic, pure style-grammar variation functions."""
from __future__ import annotations

import colorsys
import hashlib
import random
from typing import Any

from .models import Motif, Palette, TypeSpec

HUE_FAMILY_RANGES = {
    "red": (350, 12), "orange": (18, 42), "yellow": (45, 62), "green": (100, 145),
    "olive": (72, 96), "teal": (165, 190), "cyan": (190, 205), "sky": (202, 220),
    "blue": (215, 238), "cobalt": (222, 238), "indigo": (238, 258), "violet": (262, 285),
    "plum": (290, 325), "rust": (8, 24), "terracotta": (15, 32),
}


def _contrast(a: str, b: str) -> float:
    def lum(hex_color: str) -> float:
        h = hex_color.lstrip("#")
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
        return .2126 * lin[0] + .7152 * lin[1] + .0722 * lin[2]
    x, y = lum(a), lum(b)
    return (max(x, y) + .05) / (min(x, y) + .05)


def stable_seed(company: str | None, style_id: str, variant: int = 0) -> int:
    raw = f"{company or ''}\0{style_id}\0{variant}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def hue_for_family(family: str, seed: int) -> float:
    lo, hi = HUE_FAMILY_RANGES[family]
    rng = random.Random(seed ^ 0xA1B2C3)
    if hi < lo:  # red crosses the zero-degree boundary
        return (lo + rng.random() * (hi + 360 - lo)) % 360
    return lo + rng.random() * (hi - lo)


def pick_hue_family(allowed: list[str], seed: int) -> str:
    return allowed[random.Random(seed ^ 0x5EED).randrange(len(allowed))]


def _hex_from_hsl(h: float, s: float, l: float) -> str:
    rgb = colorsys.hls_to_rgb((h % 360) / 360, max(0, min(100, l)) / 100, max(0, min(100, s)) / 100)
    return "#" + "".join(f"{round(c * 255):02X}" for c in rgb)


def _choose(rng: random.Random, values: list[Any]) -> Any:
    return values[rng.randrange(len(values))]


def _harmony_hues(base: float, scheme: str) -> tuple[float, float]:
    if scheme == "complementary":
        return base, base + 180
    if scheme == "split-complementary":
        return base, base + 150
    if scheme == "monochrome":
        return base, base
    return base, base + 28  # analogous


def hue_in_families(hue: float, families: list[str]) -> bool:
    h = hue % 360
    for family in families:
        lo, hi = HUE_FAMILY_RANGES[family]
        if (lo <= hi and lo - .01 <= h <= hi + .01) or (lo > hi and (h >= lo - .01 or h <= hi + .01)):
            return True
    return False


def closest_allowed_hue(hue: float, families: list[str]) -> float:
    h = hue % 360
    if hue_in_families(h, families):
        return h
    # Keep one degree inside boundaries so 8-bit RGB quantisation cannot push a rendered hue outside.
    candidates = [v % 360 for family in families for v in (HUE_FAMILY_RANGES[family][0] + 1, HUE_FAMILY_RANGES[family][1] - 1)]
    return min(candidates, key=lambda v: abs((v - h + 180) % 360 - 180))


def generate_palette(grammar: dict, base_hue: float, seed: int) -> Palette:
    """Generate a constrained palette and guarantee 7:1 text/background contrast."""
    rules = grammar["palette"] if "palette" in grammar else grammar
    rng = random.Random(seed)
    bg_l = rng.uniform(*rules["background_lightness"])
    bg_s = rng.uniform(*rules["background_saturation"])
    text_l = rng.uniform(*rules["text_lightness"])
    # Dark grounds require light text and light grounds require dark text, even if a grammar is misconfigured.
    if bg_l < 50:
        text_l = max(text_l, 88)
    else:
        text_l = min(text_l, 18)
    background = _hex_from_hsl(base_hue, bg_s, bg_l)
    text = _hex_from_hsl(base_hue, min(12, bg_s), text_l)
    # Walk text lightness outward. A palette is never emitted unless it clears the stricter floor.
    direction = 1 if bg_l < 50 else -1
    while _contrast(text, background) < 7.0 and 0 <= text_l <= 100:
        text_l += direction
        text = _hex_from_hsl(base_hue, min(12, bg_s), text_l)
    if _contrast(text, background) < 7.0:
        text = "#FFFFFF" if bg_l < 50 else "#000000"
    scheme = _choose(rng, rules["harmony_schemes"])
    primary_h, accent_h = _harmony_hues(base_hue, scheme)
    # Analogous accents may be clamped to the style's named hue families; Frutiger uses this exclusively.
    if scheme == "analogous":
        accent_h = closest_allowed_hue(accent_h, rules["hue_families"])
    primary_s = rng.uniform(*rules["primary_saturation"])
    accent_s = rng.uniform(*rules["accent_saturation"])
    color_l = rng.uniform(52, 68) if bg_l < 50 else rng.uniform(28, 44)
    primary = _hex_from_hsl(primary_h, primary_s, color_l)
    accent = "#171717" if rules.get("fixed_accent") == "near_black" else _hex_from_hsl(accent_h, accent_s, color_l)
    surface_l = min(100, bg_l + (8 if bg_l < 50 else 2))
    return Palette(background=background, surface=_hex_from_hsl(base_hue, bg_s * .55, surface_l),
                   text=text, primary=primary, accent=accent)


def pick_font_pairing(grammar: dict, seed: int) -> TypeSpec:
    return TypeSpec(**_choose(random.Random(seed ^ 0xF00D), grammar["font_pairings"])["type"])


def pick_layout_template(grammar: dict, seed: int) -> dict:
    return dict(_choose(random.Random(seed ^ 0x1A7E), grammar["layout_templates"]))


def pick_motif(grammar: dict, industry: str | None, seed: int) -> Motif:
    pool = grammar["image_motifs"]
    rng = random.Random(seed ^ 0xA0C1F)
    hints = pool.get("industry_hints", {}).get(industry or "", [])
    return Motif(subject=_choose(rng, pool["subjects"]), composition=_choose(rng, pool["compositions"]),
                 lighting=_choose(rng, pool["lighting"]), industry_hint=_choose(rng, hints) if hints else None)


def primary_hue(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def hue_distance(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def directions_diverse(a, b) -> bool:
    return a.layout_template != b.layout_template or hue_distance(primary_hue(a.palette.primary), primary_hue(b.palette.primary)) >= 60
