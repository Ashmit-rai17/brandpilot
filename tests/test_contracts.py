import pytest
from pydantic import ValidationError
from brandpilot.models import Palette, Patch
from brandpilot.kb import lock_design_system, direction_from_style
from brandpilot.revise import apply_patch, RevisionRejected

def test_palette_invalid_hex():
    good = dict(background="#000000", surface="#111111", text="#FFFFFF", primary="#5B6CFF", accent="#8A7CFF")
    Palette(**good)
    with pytest.raises(ValidationError):
        Palette(**{**good, "background": "#12345"})

def test_patch_invalid_saturation():
    with pytest.raises(ValidationError):
        Patch(saturation="neon")

def test_patch_extra_keys_silently_dropped():
    patch = Patch(**{"palette": "red", "font": "serif"})
    assert patch.is_empty() is True
    assert not hasattr(patch, "palette")
    assert not hasattr(patch, "font")

def test_apply_patch_rejects_font_change():
    direction = direction_from_style("swiss", "x", 1)
    ds = lock_design_system(direction)
    with pytest.raises(RevisionRejected):
        apply_patch(ds, Patch(wants_font_change=True))
