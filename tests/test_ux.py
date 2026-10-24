"""Universal intents (greeting/help/status/thanks/off-topic) and suggestions accepted with "yes"."""
import copy
import json

from brandpilot.cards import parse_selection
from brandpilot.flow import ASSETS, DIRECTIONS, DONE, REVIEW_DS, REVISE_CONFIRM, handle
from brandpilot.models import DesignSystem
from tests.test_e2e_flow import BRIEF, TO_ASSETS, _to

PICK_1 = json.dumps({"action": "pick_direction", "direction_id": "dir_1"})
STAGES = {DIRECTIONS: [json.dumps(BRIEF)], REVIEW_DS: [json.dumps(BRIEF), "1"], ASSETS: TO_ASSETS,
          REVISE_CONFIRM: TO_ASSETS + ["make the colors more vibrant"], DONE: TO_ASSETS + ["done"]}


def _click(sid):
    return json.dumps({"action": "apply_suggestion", "suggestion_id": sid})


# ---------- intents ----------

def test_greeting_and_intents_leave_state_unchanged_at_every_stage(tmp_path):
    for stage, steps in STAGES.items():
        for text in ("hi", "hello!", "good morning", "@brandpilot hey", "help", "what can you do?", "status",
                     "where are we", "thanks", "thank you so much", "cool"):
            svc, s = _to(tmp_path, steps)
            before, calls = copy.deepcopy(s), svc.generate_image.calls
            r = handle(s, text, svc)
            assert s == before and svc.generate_image.calls == calls, (stage, text)
            assert "Forge" in r[0].text and "went wrong" not in r[0].text, (stage, text, r[0].text)


def test_greeting_at_empty_brief_keeps_intro_form():
    from brandpilot.brain import Brain
    from brandpilot.flow import Services, new_session
    svc = Services(brain=Brain(offline=True), generate_image=lambda p: b"")
    for text in ("hi", "good morning"):
        s = new_session()
        r = handle(s, text, svc)
        assert r[0].card_kind == "form" and r[0].text.startswith("Hi, I'm BrandPilot") and s["stage"] == "BRIEF"


def test_greeting_with_revision_still_revises(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    handle(s, "hi, make the colors more vibrant", svc)
    assert s["stage"] == REVISE_CONFIRM and s["pending_patch"]["saturation"] == "vibrant"


def test_capabilities_and_status_name_brand_and_stage(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    r = handle(s, "what can you do", svc)
    assert "Forge" in r[0].text and "Stage: Assets" in r[0].text and "make the colors more vibrant" in r[0].text
    r = handle(s, "status", svc)
    t = r[0].text
    assert "Forge" in t and "Stage: Assets" in t and "v1" in t and "poster (v1)" in t and "Next:" in t
    svc, s = _to(tmp_path, [json.dumps(BRIEF), "1"])
    assert "Stage: Design system review" in handle(s, "where are we?", svc)[0].text


def test_greeting_reports_progress(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    t = handle(s, "hi", svc)[0].text
    assert t.startswith("Hi! I'm BrandPilot") and "Forge" in t and "poster (v1)" in t


def test_intents_do_not_fire_for_json(tmp_path):
    svc, s = _to(tmp_path, [json.dumps(BRIEF)])
    handle(s, json.dumps({"action": "pick_direction", "direction_id": "dir_1", "note": "hi"}), svc)
    assert s["stage"] == REVIEW_DS


def test_off_topic_at_assets_offers_suggestions(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    r = handle(s, "what's the weather in Paris", svc)
    assert r[0].text.startswith("I can help with your brand's design. Try:") and "couldn't map" not in r[0].text
    assert s["stage"] == ASSETS and s["ds"]["version"] == 1 and r[0].card_kind == "carousel"


# ---------- direction recommendation ----------

def test_direction_recommendation_yes_picks_it(tmp_path):
    svc, s = _to(tmp_path, [])
    r = handle(s, json.dumps(BRIEF), svc)
    name = s["directions"][0]["name"]  # Dark Minimal overlaps calm/precise/premium/dev-tools the most
    assert f"I'd go with {name}:" in r[0].text and f"Say yes to use {name}, or pick the other one." in r[0].text
    assert r[0].card_kind == "carousel" and [x["kind"] for x in s["suggestions"]] == ["pick_direction"]
    handle(s, "yes", svc)
    assert s["stage"] == REVIEW_DS and s["ds"]["style_id"] == s["directions"][0]["style_id"]
    assert not s.get("suggestions")


def test_number_at_directions_still_means_direction(tmp_path):
    svc, s = _to(tmp_path, [json.dumps(BRIEF)])
    handle(s, "2", svc)
    assert s["stage"] == REVIEW_DS and s["ds"]["style_id"] == s["directions"][1]["style_id"]


# ---------- asset suggestions ----------

def test_poster_offers_numbered_suggestions_with_carousel(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    sugs = s["suggestions"]
    assert 2 <= len(sugs) <= 3 and [x["kind"] for x in sugs][-1] == "social_post"
    r = handle(s, "status", svc)  # intents keep suggestions pending
    assert s["suggestions"] == sugs
    svc, s = _to(tmp_path, TO_ASSETS[:-1])
    r = handle(s, "approve", svc)
    assert r[0].image_png and r[0].card_kind == "carousel"
    items = r[0].card_payload["items"]
    assert [i["primary_cta"]["selection"] for i in items] == [
        {"action": "apply_suggestion", "suggestion_id": x["id"]} for x in s["suggestions"]]
    assert set(items[0]) == {"id", "title", "subtitle", "badges", "secondary_text", "primary_cta"}
    for i, x in enumerate(s["suggestions"], 1):
        assert f"{i}. {x['label']}" in r[0].text


def test_yes_with_several_asks_which_one(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    before = copy.deepcopy(s)
    r = handle(s, "yes", svc)
    assert r[0].text.startswith("Which one? Reply 1, 2") and s == before


def test_yes_with_one_suggestion_applies_it(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    s["suggestions"] = [x for x in s["suggestions"] if x["kind"] == "social_post"]
    r = handle(s, "do it", svc)
    assert r[0].image_png and "social_post" in s["assets"]


def test_number_picks_patch_suggestion_with_review(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    first = s["suggestions"][0]
    assert first["kind"] == "patch"
    r = handle(s, "@brandpilot 1", svc)
    assert s["stage"] == REVISE_CONFIRM and r[0].card_kind == "review" and s["ds"]["version"] == 1
    assert {k: v for k, v in s["pending_patch"].items() if k in first["payload"]} == first["payload"]
    assert not s.get("suggestions")
    handle(s, "yes", svc)  # at REVISE_CONFIRM yes still means approve
    assert s["stage"] == ASSETS and s["ds"]["version"] == 2


def test_json_click_picks_by_id(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    social = next(x for x in s["suggestions"] if x["kind"] == "social_post")
    sel = parse_selection("@agent1qabc " + _click(social["id"]))
    assert sel == {"action": "apply_suggestion", "suggestion_id": social["id"]}
    r = handle(s, "@agent1qabc " + _click(social["id"]), svc)
    assert r[0].image_png and "social_post" in s["assets"] and "already done" not in r[0].text


def test_stale_yes_after_another_message_does_nothing(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    s["suggestions"] = s["suggestions"][:1]
    handle(s, "make it warmer", svc)
    handle(s, "cancel", svc)
    assert not s.get("suggestions")
    before = copy.deepcopy(s)
    handle(s, "yes", svc)
    assert s == before


def test_stale_click_does_nothing(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    old = s["suggestions"][0]["id"]
    handle(s, "make it warmer", svc)
    handle(s, "cancel", svc)
    before = copy.deepcopy(s)
    r = handle(s, _click(old), svc)
    assert s == before and "no longer" in r[0].text


def test_suggestions_never_include_noop(tmp_path):
    from brandpilot.flow import _suggestions
    from brandpilot.revise import apply_patch, diff
    from brandpilot.models import Patch
    svc, s = _to(tmp_path, TO_ASSETS)
    ds = DesignSystem(**s["ds"]).model_copy(update={"saturation": "vibrant", "spacing": "high"})
    sugs = _suggestions(ds, s)
    patches = [x["payload"] for x in sugs if x["kind"] == "patch"]
    assert {"saturation": "vibrant"} not in patches and {"spacing": "high"} not in patches
    assert patches == [{"saturation": "balanced"}, {"spacing": "medium"}]
    for p in patches:
        assert diff(ds, apply_patch(ds, Patch(**p)))
    warmed = ds.model_copy(update={"history": [{"patch": {"temperature": "warmer"}}]})
    assert all(x["payload"] != {"temperature": "warmer"} for x in _suggestions(warmed, s))
    s["assets"]["social_post"] = s["assets"]["poster"]
    assert _suggestions(ds, s)[-1]["kind"] == "done"
