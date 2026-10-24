from brandpilot.kb import contrast, set_saturation, styles, fonts, font_path, lock_design_system, direction_from_style
from brandpilot.models import Patch
from brandpilot.revise import RevisionRejected, apply_patch, diff
import pytest


def test_contrast_reference_values():
    assert round(contrast("#000000", "#FFFFFF"), 1) == 21.0
    assert round(contrast("#777777", "#FFFFFF"), 2) == 4.48  # known WCAG edge case


def test_vibrant_increases_saturation_keeps_hue():
    import colorsys
    a, b = "#5B6CFF", set_saturation("#9A3412", "balanced", "vibrant")
    h1, s1, _ = colorsys.rgb_to_hsv(*[int("9A3412"[i:i+2], 16) / 255 for i in (0, 2, 4)])
    h2, s2, _ = colorsys.rgb_to_hsv(*[int(b[1:][i:i+2], 16) / 255 for i in (0, 2, 4)])
    assert s2 > s1 and abs(h1 - h2) < 0.01


def test_patch_touches_only_allowed_fields():
    ds = lock_design_system(direction_from_style("editorial", "x", 1))
    new = apply_patch(ds, Patch(saturation="vibrant"))
    assert {k for k, _, _ in diff(ds, new)} <= {"saturation", "palette.primary", "palette.accent"}


def test_locked_type_rejected():
    ds = lock_design_system(direction_from_style("swiss", "x", 1))
    with pytest.raises(RevisionRejected):
        apply_patch(ds, Patch(wants_font_change=True))


def test_every_style_references_real_font_files():
    for s in styles().values():
        for role in ("heading", "body"):
            assert s["type"][role] in fonts(), (s["id"], role)
            assert font_path(s["type"][role]).exists()


def test_every_style_palette_passes_text_contrast():
    for s in styles().values():
        assert contrast(s["palette"]["text"], s["palette"]["background"]) >= 4.5, s["id"]
