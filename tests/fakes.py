"""Test doubles. placeholder_background is clearly synthetic and never presented as generated art."""
import io
import random

from PIL import Image, ImageDraw


def placeholder_background(prompt: str) -> bytes:
    rnd = random.Random(len(prompt))
    img = Image.new("RGB", (1024, 1280), (40, 60, 90))
    d = ImageDraw.Draw(img)
    for _ in range(25):
        x, y = rnd.randint(0, 1024), rnd.randint(300, 1280)
        r = rnd.randint(40, 220)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(rnd.randint(60, 255), rnd.randint(60, 200), rnd.randint(60, 255)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class CountingImage:
    def __init__(self):
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        return placeholder_background(prompt)
