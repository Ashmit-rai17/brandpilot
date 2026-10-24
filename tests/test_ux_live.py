"""Restart wording, narrated suggestion clicks and the 'working on it' trigger (live asi1.ai findings)."""
import json

from brandpilot.flow import ASSETS, REVIEW_DS, REVISE_CONFIRM, handle, is_long_action, is_restart
from tests.test_e2e_flow import BRIEF, _to

# exact text ASI:One streamed to us at 10:03:11 UTC; it is ASI:One's commentary, not a user restart
ASI1_RESTART_REWRITE = ("Alright, you've pinged BrandPilot for a restart — that's between you and it, I'm just here "
                        "watching the chaos from the cheap seats. \n\nHeads up though: a restart usually wipes its "
                        "memory of v2 being approved, so don't be shocked when it looks at you like you're a stranger. "
                        "If it comes back amnesiac, just drop the design system details again and it should pick up "
                        "where you left off.\n\nWant me to do anything while you wrangle it?")
TO_ASSETS = [json.dumps(BRIEF), "1", "approve"]


def test_restart_anywhere_in_short_messages():
    for t in ["please restart", "can we start over?", "ok restart BrandPilot", "restart"]:
        assert is_restart(t), t
    assert not is_restart(ASI1_RESTART_REWRITE)  # long commentary mentioning restart is not a request
    assert not is_restart("make the colors more vibrant")


def test_short_restart_message_resets_session(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    r = handle(s, "@brandpilot please restart", svc)
    assert s["stage"] == "BRIEF" and r[0].card_kind == "form"


def test_narrated_suggestion_click_picks_by_title(tmp_path):
    svc, s = _to(tmp_path, TO_ASSETS)
    labels = [x["label"] for x in s["suggestions"]]
    social = next(lbl for lbl in labels if "social post" in lbl.lower())
    calls = svc.generate_image.calls
    handle(s, f"The user chose '{social}'", svc)
    assert "social_post" in s["assets"] and svc.generate_image.calls == calls + 1
    svc, s = _to(tmp_path, TO_ASSETS)
    first = s["suggestions"][0]["label"]  # a patch suggestion goes to the review card
    r = handle(s, f"@brandpilot User picked {first.upper()}", svc)
    assert s["stage"] == REVISE_CONFIRM and r[0].card_kind == "review"


def test_long_action_detection(tmp_path):
    svc, s = _to(tmp_path, [json.dumps(BRIEF), "1"])
    assert s["stage"] == REVIEW_DS
    assert is_long_action(s, '@agent1q {"action":"approve_ds","approved":true}') and is_long_action(s, "yes")
    assert not is_long_action(s, '{"action":"reject_ds"}')
    svc, s = _to(tmp_path, TO_ASSETS)
    assert s["stage"] == ASSETS
    assert is_long_action(s, "social post") and is_long_action(s, "retry")
    assert not is_long_action(s, "make it warmer") and not is_long_action(s, "status")
    handle(s, "make the colors more vibrant", svc)
    assert s["stage"] == REVISE_CONFIRM and is_long_action(s, '{"action":"approve_patch"}')
