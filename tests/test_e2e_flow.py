"""Full workflow from brief to approved revision, offline. This is the demo path."""
import json

from brandpilot.brain import Brain
from brandpilot.flow import ASSETS, DIRECTIONS, DONE, REVIEW_DS, REVISE_CONFIRM, Services, handle, new_session
from tests.fakes import CountingImage

BRIEF = {"action": "submit_brief", "company": "Forge", "product": "AI productivity tool for developers",
         "audience": "senior developers", "headline": "Ship calmer, build faster", "personality": "precise, calm, premium"}


def run(s, text, svc):
    return handle(s, text if isinstance(text, str) else json.dumps(text), svc)


def test_full_demo_path(tmp_path):
    img = CountingImage()
    svc = Services(brain=Brain(offline=True), generate_image=img, data_dir=tmp_path)
    s = new_session()

    r = run(s, "hi", svc)
    assert r[0].card_kind == "form" and "company" in r[0].text

    r = run(s, BRIEF, svc)
    assert s["stage"] == DIRECTIONS and r[0].card_kind == "carousel"
    items = r[0].card_payload["items"]
    assert len(items) == 2 and items[0]["title"] != items[1]["title"]
    assert s["directions"][0]["style_id"] == "dark_minimal"  # precise/calm/premium -> dark minimal ranks first
    assert s["rejected"] is not None  # neo-brutalism clashes with calm/premium

    r = run(s, {"action": "pick_direction", "direction_id": "dir_1"}, svc)
    assert s["stage"] == REVIEW_DS and r[0].card_kind == "review"

    r = run(s, {"action": "approve_ds"}, svc)
    assert s["stage"] == ASSETS and r[0].image_png and img.calls == 1
    v1 = dict(s["ds"])
    assert "Design check" in r[0].text and "FAIL" not in r[0].text, r[0].text
    assert s["brief"]["company"] == "Forge"

    r = run(s, "make the colors more vibrant", svc)
    assert s["stage"] == REVISE_CONFIRM and r[0].card_kind == "review"
    assert s["ds"]["version"] == 1, "original kept until approval"

    r = run(s, {"action": "approve_patch"}, svc)
    v2 = s["ds"]
    assert v2["version"] == 2 and v2["saturation"] == "vibrant"
    assert v2["type"] == v1["type"] and v2["spacing"] == v1["spacing"]
    assert v2["palette"]["text"] == v1["palette"]["text"] and v2["palette"]["background"] == v1["palette"]["background"]
    assert v2["palette"]["primary"] != v1["palette"]["primary"]
    assert img.calls == 1, "vibrancy revision reuses the same background"
    assert s["assets"]["poster"]["ds_version"] == 2
    assert "Preserved" in r[0].text

    r = run(s, "social post", svc)
    assert r[0].image_png and s["assets"]["social_post"]["ds_version"] == 2

    r = run(s, "done", svc)
    assert s["stage"] == DONE and r[0].end_session and "--bp-primary" in r[0].text


def test_font_change_is_refused(tmp_path):
    svc = Services(brain=Brain(offline=True), generate_image=CountingImage(), data_dir=tmp_path)
    s = new_session()
    for t in ["hi", json.dumps(BRIEF), json.dumps({"action": "pick_direction", "direction_id": "dir_2"}), "yes"]:
        handle(s, t, svc)
    r = handle(s, "change the font to something serif", svc)
    assert "locked" in r[0].text.lower() and s["stage"] == ASSETS


def test_cancel_keeps_version(tmp_path):
    svc = Services(brain=Brain(offline=True), generate_image=CountingImage(), data_dir=tmp_path)
    s = new_session()
    for t in ["hi", json.dumps(BRIEF), "1", "approve", "make the layout tighter"]:
        handle(s, t, svc)
    assert s["stage"] == REVISE_CONFIRM
    handle(s, "cancel", svc)
    assert s["ds"]["version"] == 1 and s["stage"] == ASSETS


def test_image_failure_does_not_corrupt_state(tmp_path):
    def boom(prompt):
        raise RuntimeError("upstream 503")
    svc = Services(brain=Brain(offline=True), generate_image=boom, data_dir=tmp_path)
    s = new_session()
    for t in ["hi", json.dumps(BRIEF), "1"]:
        handle(s, t, svc)
    r = handle(s, "approve", svc)
    assert "failed" in r[0].text and s["ds"]["version"] == 1 and s["assets"] == {}
