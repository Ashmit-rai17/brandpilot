"""Full workflow from brief to approved revision, offline. This is the demo path."""
import json

from brandpilot.brain import Brain
from brandpilot.flow import ASSETS, DIRECTIONS, DONE, REVIEW_DS, REVISE_CONFIRM, Services, handle, new_session
from brandpilot.models import Brief
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


# ---------- planner-narrated (prose) card clicks ----------

def _svc(tmp_path):
    return Services(brain=Brain(offline=True), generate_image=CountingImage(), data_dir=tmp_path)


def _to(tmp_path, steps):
    svc, s = _svc(tmp_path), new_session()
    for t in steps:
        handle(s, t, svc)
    return svc, s


def test_prose_confirm_design_system(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1"])
    assert s["stage"] == REVIEW_DS
    r = handle(s, "The user confirmed the design system", svc)
    assert s["stage"] == ASSETS and r[0].image_png


def test_prose_reject_design_system(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1"])
    handle(s, "The user chose to reject the design system", svc)
    assert s["stage"] == DIRECTIONS


def test_prose_approve_patch(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1", "approve", "make the colors more vibrant"])
    assert s["stage"] == REVISE_CONFIRM
    handle(s, "The user approved the proposed change", svc)
    assert s["stage"] == ASSETS and s["ds"]["version"] == 2


def test_prose_cancel_patch(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1", "approve", "make the colors more vibrant"])
    handle(s, "The user chose to cancel the proposed change", svc)
    assert s["stage"] == ASSETS and s["ds"]["version"] == 1


def test_prose_pick_direction_variants(tmp_path):
    for text in ("The user picked direction dir_2", "The user picked dir 2"):
        svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF)])
        handle(s, text, svc)
        assert s["stage"] == REVIEW_DS and s["ds"]["style_id"] == s["directions"][1]["style_id"], text


def test_parse_selection_spaced_action():
    from brandpilot.cards import parse_selection
    assert parse_selection("The user clicked approve ds") == {"action": "approve_ds"}


def test_prose_form_submit_uses_text(tmp_path):
    svc = _svc(tmp_path)
    s = new_session()
    handle(s, "The user submitted the form (submit_brief).\ncompany: Forge\nproduct: AI productivity tool\n"
              "audience: senior developers\nheadline: Ship calmer, build faster", svc)
    assert s["stage"] == DIRECTIONS


# ---------- out-of-stage clicks and long planner prompts (real ASI:One traffic) ----------

ADDR = "@agent1q2xyzlivetrafficaddress"
LONG_PROMPT = (ADDR + " We are testing BrandPilot's complete interactive workflow. Please follow every step in order. "
               "Step 1 — Brand brief\nStart the normal flow and wait for my choice before continuing.")


def test_long_prompt_does_not_pick_direction(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF)])
    assert len(LONG_PROMPT) > 20 and "Step 1" in LONG_PROMPT
    r = handle(s, LONG_PROMPT, svc)
    assert s["stage"] == DIRECTIONS and r[0].card_kind == "carousel" and "Which direction" in r[0].text


def test_short_number_still_picks_direction(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF)])
    handle(s, "1", svc)
    assert s["stage"] == REVIEW_DS


def test_pick_direction_click_at_review_switches(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1"])
    first = s["ds"]["style_id"]
    r = handle(s, ADDR + ' {"action":"pick_direction","direction_id":"dir_2","approved":true}', svc)
    assert s["stage"] == REVIEW_DS and r[0].card_kind == "review"
    assert s["ds"]["style_id"] == s["directions"][1]["style_id"] != first


def test_stale_actions_at_assets_are_status_only(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1", "approve"])
    img = svc.generate_image
    assert s["stage"] == ASSETS and img.calls == 1
    for text in (ADDR + ' {"action":"approve_ds","approved":true}',
                 "The user approved the design system", "The user confirmed the design system"):
        r = handle(s, text, svc)
        assert s["stage"] == ASSETS and img.calls == 1 and s["ds"]["version"] == 1, text
        assert "already done" in r[0].text and "design system v1" in r[0].text, text
        assert not r[0].image_png


def test_stale_actions_at_revise_confirm_keep_pending(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1", "approve", "make the colors more vibrant"])
    for act in ("approve_ds", "reject_ds", "pick_direction", "submit_brief"):
        r = handle(s, json.dumps({"action": act}), svc)
        assert s["stage"] == REVISE_CONFIRM and s["pending_ds"] and r[0].card_kind == "review", act
        assert "Approve or cancel the proposed change v1 to v2" in r[0].text


REVISIONS = [("make the colors more vibrant", "saturation", "vibrant"), ("more vibrant", "saturation", "vibrant"),
             ("can you make it pop", "saturation", "vibrant"), ("brighter colours", "saturation", "vibrant"),
             ("warmer", "temperature", "warmer"), ("make it cooler", "temperature", "cooler"),
             ("more breathing room", "spacing", "high"), ("tighter layout", "spacing", "low"),
             ("change the image to something more organic", "image_style", None)]


def _ds_for_revisions(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1", "approve"])
    from brandpilot.models import DesignSystem
    ds = DesignSystem(**s["ds"])
    return ds.model_copy(update={"spacing": "medium", "saturation": "balanced"})


def _check(patch, field, value):
    got = getattr(patch, field)
    assert got and not patch.is_empty() and (value is None or got == value), (field, got)


def test_revision_mapping_rules(tmp_path):
    ds = _ds_for_revisions(tmp_path)
    for req, field, value in REVISIONS:
        _check(Brain(offline=True).write_patch(req, ds), field, value)


def test_revision_mapping_asi1(tmp_path, monkeypatch):
    ds = _ds_for_revisions(tmp_path)
    for req, field, value in REVISIONS:
        reply = {field: value or "organic natural textures"}
        monkeypatch.setattr("brandpilot.asi1.chat_json", lambda *a, _r=reply, **k: dict(_r))
        brain = Brain(offline=False)
        _check(brain.write_patch(req, ds), field, value)
        assert brain.last_source == "asi1", req


def test_font_change_serif_rejected(tmp_path):
    from brandpilot.revise import RevisionRejected, apply_patch
    import pytest
    ds = _ds_for_revisions(tmp_path)
    patch = Brain(offline=True).write_patch("change the font to serif", ds)
    assert patch.wants_font_change
    with pytest.raises(RevisionRejected):
        apply_patch(ds, patch)


def test_addressed_short_number_picks_direction(tmp_path):
    addr = "@agent1qw0pqhpynjdc7hx9r0q8g9ng6yzp3cflw7wpm5kfc8j78dy9qq3qudhsf7r"
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF)])
    handle(s, addr + " 1", svc)
    assert s["stage"] == REVIEW_DS and s["ds"]["style_id"] == s["directions"][0]["style_id"]


def test_direction_phrase_picks_regardless_of_length(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF)])
    handle(s, "I'll take direction 2", svc)
    assert s["stage"] == REVIEW_DS and s["ds"]["style_id"] == s["directions"][1]["style_id"]


def test_revision_with_approval_words_is_not_swallowed(tmp_path):
    for text in ("approve the design system and make it warmer",
                 "I approve, make the colors more vibrant in this direction"):
        svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1", "approve"])
        handle(s, text, svc)
        assert s["stage"] == REVISE_CONFIRM, text


def test_background_color_requests_do_not_set_image_style(tmp_path):
    ds = _ds_for_revisions(tmp_path)
    for req in ("make the background more vibrant", "background to be warmer"):
        assert Brain(offline=True).write_patch(req, ds).image_style is None, req


def test_stale_action_without_pending_ds_does_not_crash(tmp_path):
    svc, s = _to(tmp_path, ["hi", json.dumps(BRIEF), "1", "approve", "make the colors more vibrant"])
    s["pending_ds"] = None
    r = handle(s, json.dumps({"action": "approve_ds"}), svc)
    assert "went wrong" not in r[0].text


# Live asi1.ai, 24 Oct 09:13 UTC: old session at ASSETS received a new brief and "@brandpilot restart".
FORGE_BRIEF = ("@brandpilot I'm launching Forge, an AI productivity tool for senior developers. Calm, precise, "
               "premium. Headline: Ship calmer, build faster.")
TO_ASSETS = [json.dumps(BRIEF), "1", "approve"]


def test_new_brief_at_assets_suggests_restart(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    calls = svc.generate_image.calls
    r = handle(s, FORGE_BRIEF, svc)
    assert s["stage"] == ASSETS and "Looks like a new brand" in r[0].text
    assert svc.generate_image.calls == calls and s["ds"]["version"] == 1


def test_new_brief_at_revise_confirm_suggests_restart(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS + ["make the colors more vibrant"])
    r = handle(s, "We're Lumen, a budgeting app for students. Headline: Money, made simple.", svc)
    assert s["stage"] == REVISE_CONFIRM and "Looks like a new brand" in r[0].text


def test_revision_still_works_at_assets(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    handle(s, "@brandpilot make the colors more vibrant", svc)
    assert s["stage"] == REVISE_CONFIRM


def test_mentioned_restart_and_done(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    r = handle(s, "@brandpilot restart", svc)
    assert s["stage"] == "BRIEF" and r[0].card_kind == "form"
    svc, s = _to(tmp_path, TO_ASSETS)
    handle(s, "@brandpilot done", svc)
    assert s["stage"] == DONE


FORGE_EXACT = ("I'm launching Forge, an AI productivity tool for senior developers. Calm, precise, premium. "
               "Headline: Ship calmer, build faster.")
KAAPI_STYLE = ("Brand name: KAAPI CULTURE\nProduct: Contemporary South Indian specialty filter coffee\n"
               "Audience: Urban Indians aged 20-35")


def _no_patch(*a, **k):
    raise AssertionError("a brief must never reach write_patch")


def test_exact_brief_at_assets_never_reaches_write_patch(tmp_path, monkeypatch):
    for brief in (FORGE_EXACT, "@brandpilot " + FORGE_EXACT, KAAPI_STYLE):
        svc, s = _to(tmp_path, TO_ASSETS)
        monkeypatch.setattr(svc.brain, "write_patch", _no_patch)
        r = handle(s, brief, svc)
        assert s["stage"] == ASSETS and "Looks like a new brand" in r[0].text and s.get("pending_ds") is None


def test_vibrant_at_assets_still_becomes_a_patch(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    handle(s, "make the colors more vibrant", svc)
    assert s["stage"] == REVISE_CONFIRM and s["pending_patch"]["saturation"] == "vibrant"


def test_offline_brief_from_free_text():
    b = Brain(offline=True).extract_brief(
        "I'm launching Forge, an AI productivity tool for senior developers. Calm, precise, premium. "
        "Headline: Ship calmer, build faster.", Brief())
    assert (b.company, b.product, b.audience, b.headline) == (
        "Forge", "AI productivity tool", "senior developers", "Ship calmer, build faster")
    assert b.missing() == []
    assert b.personality == ["calm", "precise", "premium"] and b.positioning == "premium"
    assert b.industry == "dev-tools"

    b = Brain(offline=True).extract_brief(
        "We're Lumen, a budgeting app for students. Playful and friendly. Headline: Money, made simple.", Brief())
    assert (b.company, b.product, b.audience, b.headline) == ("Lumen", "budgeting app", "students", "Money, made simple")
    assert b.missing() == [] and b.personality == ["playful", "friendly"]


def test_offline_brief_never_invents_company():
    b = Brain(offline=True).extract_brief("I'm launching an AI tool for developers.", Brief())
    assert b.company is None
