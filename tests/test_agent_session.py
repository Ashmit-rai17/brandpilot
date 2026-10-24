"""New ASI:One chats start a fresh design session (agent.py helpers; no network, agent is not run)."""
from datetime import datetime, timezone
from uuid import uuid4

from uagents_core.contrib.protocols.chat import ChatMessage, MetadataContent, StartSessionContent, TextContent

import agent
from brandpilot.flow import new_session

BRIEF = "I'm launching Forge, an AI productivity tool for senior developers. Headline: Ship calmer, build faster."


def _msg(*content):
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=list(content))


def test_live_new_chat_message_shape_resets_old_session():
    # exact content types seen live at 09:12:45 UTC: StartSession, Text, reply-timeout, x-session-id
    m = _msg(StartSessionContent(type="start-session"), TextContent(type="text", text=BRIEF),
             MetadataContent(type="metadata", metadata={"reply-timeout": "120"}),
             MetadataContent(type="metadata", metadata={"x-session-id": "a36148d5-7147-4959-bd61-988c09a8e840"}))
    start, chat_id = agent._chat_session(m)
    assert start and chat_id == "a36148d5-7147-4959-bd61-988c09a8e840"
    old = new_session() | {"stage": "ASSETS", "chat_session": "11111111-0000-0000-0000-000000000000"}
    assert agent._is_new_chat(old, start, chat_id)
    assert agent._is_new_chat(new_session() | {"stage": "ASSETS"}, start, chat_id)  # no chat id stored yet


def test_same_chat_or_plain_message_keeps_session():
    same = new_session() | {"stage": "ASSETS", "chat_session": "a36148d5"}
    start, chat_id = agent._chat_session(_msg(StartSessionContent(type="start-session"),
                                              MetadataContent(type="metadata", metadata={"x-session-id": "a36148d5"})))
    assert not agent._is_new_chat(same, start, chat_id)
    start, chat_id = agent._chat_session(_msg(TextContent(type="text", text="@brandpilot make it warmer")))
    assert (start, chat_id) == (False, None) and not agent._is_new_chat(same, start, chat_id)


def test_start_session_without_chat_id_resets():
    start, chat_id = agent._chat_session(_msg(StartSessionContent(type="start-session"), TextContent(type="text", text=BRIEF)))
    assert agent._is_new_chat(new_session() | {"stage": "ASSETS"}, start, chat_id)


FORGE = ("I'm launching Forge, an AI productivity tool for senior developers. Calm, precise, premium. "
         "Headline: Ship calmer, build faster.")


def test_duplicate_brief_is_skipped():
    s = "agent1q0p0gmk5f3-dup-test"
    assert agent._duplicate(s, "m1", FORGE, 1000.0) is None
    assert agent._duplicate(s, "m1", FORGE, 1001.0) == "duplicate msg_id skipped"
    assert agent._duplicate(s, "m2", FORGE, 1030.0) == "duplicate text skipped"   # new msg_id, same text, 30s later
    assert agent._duplicate(s, "m3", FORGE, 1030.0 + 121) is None                 # window expired
    assert agent._duplicate("another-sender", "m4", FORGE, 1031.0) is None        # per sender


def test_retry_and_restart_are_never_skipped():
    s = "agent1q-retry-test"
    for i, t in enumerate(["retry", "retry", "@brandpilot restart", "@brandpilot restart"]):
        assert agent._duplicate(s, f"r{i}", t, 2000.0 + i) is None


# Live 24 Oct 10:02-10:04 UTC: ASI:One streamed its own assistant reply to us.
COMMENTARY = ("Well, that's beautifully broken — or fixed? Hard to tell with this thing. 🔧\n\nBrandPilot's back up and "
              "cranked out v2 like nothing happened: new accent color, more vibrancy, and the fonts survived the apocalypse.")


def test_asi1_stream_chunk_and_empty_messages_are_ignored():
    from uagents_core.contrib.protocols.chat import EndStreamContent
    chunk = _msg(TextContent(type="text", text=COMMENTARY), MetadataContent(type="metadata", metadata={"index": "0"}))
    assert agent._ignore_reason(chunk, COMMENTARY) == "ASI:One stream chunk ignored"
    assert agent._ignore_reason(_msg(EndStreamContent(type="end-stream", stream_id=uuid4())), "") \
        == "message without text ignored"


def test_real_messages_and_card_clicks_are_not_ignored():
    click = '@agent1qw0pqhpynjdc7hx9r0q8g9ng6yzp3cflw7wpm5kfc8j78dy9qq3qudhsf7r {"action":"approve_ds","approved":true}'
    assert agent._ignore_reason(_msg(TextContent(type="text", text=click)), click) is None
    assert agent._ignore_reason(_msg(TextContent(type="text", text="@brandpilot restart")), "@brandpilot restart") is None
    new_chat = _msg(StartSessionContent(type="start-session"), TextContent(type="text", text=BRIEF),
                    MetadataContent(type="metadata", metadata={"reply-timeout": "120"}),
                    MetadataContent(type="metadata", metadata={"x-session-id": "a36148d5"}))
    assert agent._ignore_reason(new_chat, BRIEF) is None
    assert agent._ignore_reason(_msg(StartSessionContent(type="start-session")), "") is None


def test_poster_markdown_rides_in_the_text_message():
    url = "https://raw.githubusercontent.com/Ashmit-rai17/brandpilot/assets/posters/poster_v1-ebcb136c.png"
    text = "Design system approved. Poster built from design system v1.\n\nWhat I'd do next:\n1. Make the colors more vibrant"
    out = agent._with_image(text, "poster_v1.png", url)
    assert out.startswith(f"![poster_v1.png]({url})\n\n") and out.endswith(text)
