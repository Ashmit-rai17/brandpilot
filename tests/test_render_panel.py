"""The plain contrast panel (styles with panel "none") is fully opaque: no background noise shows through."""
import io

import numpy as np
from PIL import Image

from brandpilot.kb import direction_from_style, lock_design_system
from brandpilot.models import Brief
from brandpilot.render import compose


def test_plain_panel_is_opaque():
    ds = lock_design_system(direction_from_style("swiss", "x", 1))
    noise = Image.fromarray(np.random.default_rng(0).integers(0, 256, (1024, 1024, 3), dtype=np.uint8))
    buf = io.BytesIO()
    noise.save(buf, "PNG")
    brief = Brief(company="Forge", product="AI productivity tool", audience="senior developers",
                  headline="Ship calmer, build faster")
    img, _, layout = compose(buf.getvalue(), ds, brief, "poster")
    assert ds.panel == "none" and layout["panel"]
    strip = np.asarray(img)[95:110, 70:880]  # inside the top panel, above the headline
    bg = [int(ds.palette.background[i:i + 2], 16) for i in (1, 3, 5)]
    assert (strip == bg).all()
