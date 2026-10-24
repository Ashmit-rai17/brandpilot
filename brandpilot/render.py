"""Compose assets: generated background + programmatic typography + measured checks.

Every check here is computed from the rendered pixels or the actual font sizes used.
Nothing is reported as passed unless it was evaluated.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .kb import contrast_ratio_lum, font_path, fonts, luminance, margin_ratio
from .models import Brief, CheckResult, DesignSystem

SIZES = {"poster": (1080, 1350), "social_post": (1080, 1080)}
SAT_LEVEL = {"muted": 0.6, "balanced": 1.0, "vibrant": 1.45}


def load_font(font_id: str, size: int, bold: bool) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(font_path(font_id)), size)
    weight = fonts()[font_id]["weights"]["bold" if bold else "regular"]
    if weight:
        try:
            f.set_variation_by_name(weight)
        except Exception:  # static font or name mismatch: keep default instance
            pass
    return f


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def wrap(text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    # Rag rule: never leave a single orphaned word on the last line.
    if len(lines) > 1 and len(lines[-1].split()) == 1 and len(lines[-2].split()) > 1:
        prev = lines[-2].split()
        moved = f"{prev[-1]} {lines[-1]}"
        if font.getlength(moved) <= max_w:
            lines[-2], lines[-1] = " ".join(prev[:-1]), moved
    return lines


def _lum_array(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB"), dtype=np.float64) / 255.0
    lin = np.where(a <= 0.03928, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def worst_contrast(base: Image.Image, box, text_hex: str) -> float:
    """Contrast of a text color against the 5th and 95th luminance percentile under its box."""
    x0, y0, x1, y1 = [int(v) for v in box]
    region = _lum_array(base.crop((max(0, x0), max(0, y0), x1, y1)))
    if region.size == 0:
        return 0.0
    tl = luminance(text_hex)
    lo, hi = np.percentile(region, 5), np.percentile(region, 95)
    return min(contrast_ratio_lum(tl, lo), contrast_ratio_lum(tl, hi))


def compose(bg_png: bytes, ds: DesignSystem, brief: Brief, asset_type: str = "poster",
            bg_saturation: str | None = None) -> tuple[Image.Image, list[CheckResult], dict]:
    W, H = SIZES[asset_type]
    margin = round(margin_ratio()[ds.spacing] * min(W, H))
    pal = ds.palette

    bg = cover(Image.open(io.BytesIO(bg_png)), W, H)
    # Saturation revisions reuse the same background and only change color intensity.
    gen_sat = bg_saturation or ds.saturation
    factor = SAT_LEVEL[ds.saturation] / SAT_LEVEL[gen_sat]
    if abs(factor - 1) > 1e-6:
        bg = ImageEnhance.Color(bg).enhance(factor)

    # ----- type sizes from the locked scale -----
    max_w = W - 2 * margin
    head_size = round(W * 0.115)
    while True:
        head_font = load_font(ds.type.heading, head_size, bold=True)
        lines = wrap(brief.headline or brief.company or "", head_font, max_w)
        widest = max(head_font.getlength(l) for l in lines)
        if (len(lines) <= 3 and widest <= max_w) or head_size <= 48:
            break
        head_size -= 4
    sub_size = max(24, round(head_size / ds.type.scale ** 2))
    sub_font = load_font(ds.type.body, sub_size, bold=False)
    brand_font = load_font(ds.type.body, sub_size, bold=True)
    leading = 1.08
    sub_lines = wrap((brief.product or "")[:90], sub_font, max_w)[:2]

    # ----- layout boxes (computed before drawing, so contrast is measured on what's under the text) -----
    x = margin
    y = margin
    head_boxes = []
    for l in lines:
        b = head_font.getbbox(l)
        head_boxes.append((l, (x, y), (x + b[0], y + b[1], x + b[2], y + b[3])))
        y += round(head_size * leading)
    y += round(sub_size * 0.9)
    sub_boxes = []
    for l in sub_lines:
        b = sub_font.getbbox(l)
        sub_boxes.append((l, (x, y), (x + b[0], y + b[1], x + b[2], y + b[3])))
        y += round(sub_size * 1.45)
    brand = (brief.company or "")[:40]
    bsize = sub_size
    while brand_font.getlength(brand) > max_w and bsize > 14:
        bsize -= 2
        brand_font = load_font(ds.type.body, bsize, bold=True)
    bb = brand_font.getbbox(brand)
    by = H - margin - (bb[3] - bb[1]) - bb[1]
    brand_box = (brand, (x, by), (x + bb[0], by + bb[1], x + bb[2], by + bb[3]))
    bar_h = max(6, round(sub_size * 0.22))
    bar = (x, brand_box[2][1] - bar_h - round(sub_size * 0.6), x + round(sub_size * 2.2),
           brand_box[2][1] - round(sub_size * 0.6))

    text_block = _union([b[2] for b in head_boxes + sub_boxes])
    bottom_block = _union([brand_box[2], bar])

    def pick_text_color(base_img):
        options = [pal.text, pal.background]
        scored = [(min(worst_contrast(base_img, bx[2], c) for bx in head_boxes + sub_boxes), c) for c in options]
        return max(scored)

    base = bg.copy()
    panel_used = ds.panel != "none"
    score, text_color = pick_text_color(base)
    if panel_used or score < 4.5:
        panel_used = True
        base = _draw_panels(bg, ds, [text_block, bottom_block], pad=round(sub_size * 0.9))
        score, text_color = pick_text_color(base)

    # ----- draw -----
    out = base.copy()
    d = ImageDraw.Draw(out)
    for l, pos, _ in head_boxes:
        d.text(pos, l, font=head_font, fill=text_color)
    for l, pos, _ in sub_boxes:
        d.text(pos, l, font=sub_font, fill=text_color)
    d.rectangle(bar, fill=pal.primary)
    brand_color = text_color
    d.text(brand_box[1], brand, font=brand_font, fill=brand_color)

    # ----- checks (all measured) -----
    head_c = min(worst_contrast(base, b[2], text_color) for b in head_boxes)
    sub_c = min([worst_contrast(base, b[2], text_color) for b in sub_boxes] or [99])
    all_boxes = [b[2] for b in head_boxes + sub_boxes] + [brand_box[2]]
    min_edge = min(min(b[0], b[1], W - b[2], H - b[3]) for b in all_boxes)
    eff_scale = (head_size / sub_size) ** 0.5
    families = {fonts()[ds.type.heading]["family"], fonts()[ds.type.body]["family"]}
    checks = [
        CheckResult(name="Headline contrast", value=f"{head_c:.1f}:1", threshold=">= 3.0:1 (WCAG AA large)",
                    passed=head_c >= 3.0, note="worst case vs 5th/95th percentile of pixels under the text"),
        CheckResult(name="Body text contrast", value=f"{sub_c:.1f}:1" if sub_boxes else "n/a",
                    threshold=">= 4.5:1 (WCAG AA)", passed=sub_c >= 4.5),
        CheckResult(name="Margin", value=f"{min_edge}px", threshold=f">= {margin}px ({ds.spacing} spacing)",
                    passed=min_edge >= margin - 1),
        CheckResult(name="Type scale", value=f"{head_size}px / {sub_size}px = {eff_scale:.2f} per step",
                    threshold=f"{ds.type.scale} per step (+/- 5%)",
                    passed=abs(eff_scale - ds.type.scale) / ds.type.scale <= 0.05),
        CheckResult(name="Font families", value=", ".join(sorted(families)), threshold="max 2",
                    passed=len(families) <= 2),
    ]
    layout = {"size": [W, H], "margin": margin, "head_size": head_size, "sub_size": sub_size,
              "lines": lines, "text_color": text_color, "panel": panel_used}
    return out, checks, layout


def _union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _draw_panels(bg: Image.Image, ds: DesignSystem, blocks, pad: int) -> Image.Image:
    img = bg.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pal = ds.palette
    for (x0, y0, x1, y1) in blocks:
        r = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        if ds.panel == "brutal":
            off = max(8, pad // 2)
            d.rectangle((r[0] + off, r[1] + off, r[2] + off, r[3] + off), fill=(17, 17, 17, 255))
            d.rectangle(r, fill=_hex_rgb(pal.surface) + (255,), outline=(17, 17, 17, 255), width=5)
        elif ds.panel == "glass":
            d.rounded_rectangle(r, radius=pad, fill=(255, 255, 255, 200), outline=(255, 255, 255, 255), width=3)
        else:
            d.rectangle(r, fill=_hex_rgb(pal.background) + (255,))
    return Image.alpha_composite(img, layer).convert("RGB")


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
