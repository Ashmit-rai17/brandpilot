"""Data contract tests (Prashant's Task 2). python -m pytest -q"""
import json
import pytest
from pydantic import ValidationError

from brandpilot.kb import KNOWLEDGE, direction_from_style, font_path, fonts, lock_design_system, styles
from brandpilot.models import Palette, Patch, TypeSpec
from brandpilot.revise import RevisionRejected, apply_patch


def test_invalid_palette_hex_raises_validation_error():
    with pytest.raises(ValidationError):
        Palette(
            background="#12345",  # 5 characters instead of 6
            surface="#FFFFFF",
            text="#000000",
            primary="#FF0000",
            accent="#00FF00",
        )

    with pytest.raises(ValidationError):
        Palette(
            background="123456",  # missing leading '#'
            surface="#FFFFFF",
            text="#000000",
            primary="#FF0000",
            accent="#00FF00",
        )

    with pytest.raises(ValidationError):
        Palette(
            background="#GGGGGG",  # non-hex character
            surface="#FFFFFF",
            text="#000000",
            primary="#FF0000",
            accent="#00FF00",
        )


def test_patch_invalid_saturation_raises_validation_error():
    with pytest.raises(ValidationError):
        Patch(saturation="neon")


def test_patch_extra_key_rejected_upstream():
    allowed_keys = {"saturation", "temperature", "spacing", "image_style", "wants_font_change", "reason"}
    assert set(Patch.model_fields.keys()) == allowed_keys
    # Extra keys are not accepted as valid fields on Patch contract
    p = Patch(saturation="vibrant")
    assert not hasattr(p, "extra_key")


def test_unknown_font_id_raises_key_error():
    with pytest.raises(KeyError):
        font_path("unknown_font_id_xyz")


def test_typespec_scale_bounds():
    with pytest.raises(ValidationError):
        TypeSpec(heading="inter", body="inter", scale=0.9)  # scale < 1.1

    with pytest.raises(ValidationError):
        TypeSpec(heading="inter", body="inter", scale=2.0)  # scale > 1.7


def test_every_style_fonts_exist_and_extended_for_references():
    available_styles = styles()
    available_fonts = fonts()

    # Check all styles have registered fonts with existing files
    for s in available_styles.values():
        for role in ("heading", "body"):
            font_id = s["type"][role]
            assert font_id in available_fonts, f"{s['id']}: {role} font {font_id} not in typography.json"
            assert font_path(font_id).exists(), f"{s['id']}: font file for {font_id} missing on disk"

    # Extend check for references.json
    refs_file = KNOWLEDGE / "references.json"
    if refs_file.exists():
        refs_data = json.loads(refs_file.read_text())
        for ref in refs_data.get("references", []):
            style_id = ref.get("style_id")
            assert style_id in available_styles, f"Reference {ref.get('id')} has unknown style_id: {style_id}"
            ref_style = available_styles[style_id]
            for role in ("heading", "body"):
                font_id = ref_style["type"][role]
                assert font_id in available_fonts
                assert font_path(font_id).exists()


def test_locked_font_change_raises_revision_rejected():
    ds = lock_design_system(direction_from_style("editorial", "test", 1))
    assert "type" in ds.locked
    with pytest.raises(RevisionRejected):
        apply_patch(ds, Patch(wants_font_change=True))


def test_empty_patch_raises_revision_rejected():
    ds = lock_design_system(direction_from_style("swiss", "test", 1))
    with pytest.raises(RevisionRejected):
        apply_patch(ds, Patch())
