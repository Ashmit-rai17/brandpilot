"""Regression coverage for the reviewed variation-sheet rendering defects."""
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from brandpilot.kb import direction_from_style, lock_design_system, styles
from brandpilot.models import Brief
from brandpilot.render import compose
from brandpilot.variation import generate_palette, hue_for_family, hue_in_families, pick_hue_family


def _render(company, product, industry, style_id, headline, busy=False):
    direction = direction_from_style(style_id, "regression", 1, company=company, industry=industry)
    ds = lock_design_system(direction)
    if busy:
        image = Image.fromarray(np.random.default_rng(direction.seed).integers(0, 256, (1350, 1080, 3), dtype=np.uint8))
    else:
        image = Image.new("RGB", (1080, 1350), ds.palette.background)
    buf = BytesIO(); image.save(buf, "PNG")
    return compose(buf.getvalue(), ds, Brief(company=company, product=product, industry=industry, headline=headline))


def _intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


@pytest.mark.parametrize("company,product,industry,headline", [
    ("Morrow", "A calmer money app", "fintech", "Money, made clear"),
    ("Serein", "Daily ritual wellness", "wellness", "Feel more like you"),
])
def test_editorial_bottom_variations_keep_identity_one_body_line_from_text(company, product, industry, headline):
    _, checks, layout = _render(company, product, industry, "editorial", headline)
    assert layout["layout_template"] == "editorial_lower"
    text_bottom = max(b[3] for b in layout["headline_boxes"] + layout["subline_boxes"])
    identity_bottom = max(layout["brand_box"][3], layout["accent_bar"][3])
    assert text_bottom - identity_bottom >= layout["sub_size"]
    assert next(c for c in checks if c.name == "Layout collisions").passed


def test_forge_neo_brutal_identity_panel_never_intersects_main_panel():
    _, checks, layout = _render("Forge", "AI developer tools", "dev-tools", "neo_brutalism", "Ship with clarity")
    assert len(layout["panel_boxes"]) == 2
    assert not _intersects(*layout["panel_boxes"])
    assert next(c for c in checks if c.name == "Layout collisions").passed


def test_forge_swiss_busy_subline_triggers_measured_fallback_panel():
    _, checks, layout = _render("Forge", "AI developer tools", "dev-tools", "swiss", "Ship with clarity", busy=True)
    assert layout["panel"]
    assert layout["busyness"] > .12
    assert next(c for c in checks if c.name == "Text busyness").passed


def test_frutiger_primary_and_accent_never_leave_allowed_hue_families():
    grammar = styles()["frutiger_aero"]["grammar"]
    families = grammar["palette"]["hue_families"]
    for seed in range(200):
        family = pick_hue_family(families, seed)
        palette = generate_palette(grammar, hue_for_family(family, seed), seed)
        from brandpilot.variation import primary_hue
        assert hue_in_families(primary_hue(palette.primary), families)
        assert hue_in_families(primary_hue(palette.accent), families)
