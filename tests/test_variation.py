from io import BytesIO

import numpy as np
from PIL import Image

from brandpilot.asi1 import compile_prompt
from brandpilot.kb import contrast, direction_from_style, lock_design_system, styles
from brandpilot.models import Brief, Patch
from brandpilot.render import compose
from brandpilot.revise import apply_patch, diff
from brandpilot.variation import directions_diverse, generate_palette, hue_for_family, pick_hue_family, stable_seed


def test_variation_is_reproducible():
    a = direction_from_style("editorial", "x", 1, company="Cedar", industry="food")
    b = direction_from_style("editorial", "x", 1, company="Cedar", industry="food")
    assert a.model_dump() == b.model_dump()
    assert stable_seed("Cedar", "editorial", 2) == stable_seed("Cedar", "editorial", 2)


def test_brands_in_one_style_do_not_share_a_palette():
    a = direction_from_style("swiss", "x", 1, company="Aster")
    b = direction_from_style("swiss", "x", 1, company="Beacon")
    assert a.palette != b.palette


def test_every_generated_palette_clears_seven_to_one_for_200_seeds_per_style():
    for style in styles().values():
        rules = style["grammar"]["palette"]
        for seed in range(200):
            family = pick_hue_family(rules["hue_families"], seed)
            palette = generate_palette(style["grammar"], hue_for_family(family, seed), seed)
            assert contrast(palette.text, palette.background) >= 7.0, (style["id"], seed, palette)


def test_style_invariants_hold_for_generated_layouts_and_headings():
    typography = {x["id"]: x for x in __import__("json").loads(open("knowledge/typography.json").read())["fonts"]}
    for style in styles().values():
        direction = direction_from_style(style["id"], "x", 1, company="Invariant", industry="saas")
        grammar = style["grammar"]
        template = next(x for x in grammar["layout_templates"] if x["id"] == direction.layout_template)
        for key, value in grammar["layout_invariants"].items():
            assert template[key] == value
        assert typography[direction.type.heading]["class"] in grammar["heading_classes"]


def test_two_directions_are_diverse():
    a = direction_from_style("dark_minimal", "x", 1, company="Orbit", industry="saas")
    b = direction_from_style("editorial", "x", 2, company="Orbit", industry="saas")
    assert directions_diverse(a, b)


def test_variation_patch_changes_only_its_allowed_fields():
    ds = lock_design_system(direction_from_style("frutiger_aero", "x", 1, company="Moss", industry="wellness"))
    new = apply_patch(ds, Patch(variation=True), company="Moss", industry="wellness")
    allowed = {"seed", "variant", "palette.background", "palette.surface", "palette.text", "palette.primary",
               "palette.accent", "layout_template", "motif.subject", "motif.composition", "motif.lighting",
               "motif.industry_hint", "hue_family"}
    assert {key for key, _, _ in diff(ds, new)} <= allowed
    assert new.type == ds.type


def test_bottom_template_prompt_uses_lower_third_copy_space():
    d = direction_from_style("swiss", "x", 1, company="Bottom", industry="fintech")
    ds = lock_design_system(d).model_copy(update={"layout_template": "swiss_lower"})
    assert "lower third calm and uncluttered" in compile_prompt(ds, "poster")


def test_none_template_still_gets_contrast_fallback_panel_on_busy_background():
    ds = lock_design_system(direction_from_style("swiss", "x", 1, company="Noise", industry="saas")).model_copy(
        update={"layout_template": "swiss_top"})
    noise = Image.fromarray(np.random.default_rng(4).integers(0, 256, (1080, 1080, 3), dtype=np.uint8), "RGB")
    buf = BytesIO(); noise.save(buf, format="PNG")
    _, _, layout = compose(buf.getvalue(), ds, Brief(company="Noise", product="A busy product", headline="Make noise useful"))
    assert styles()["swiss"]["grammar"]["layout_templates"][0]["panel"] == "none"
    assert layout["panel"]
