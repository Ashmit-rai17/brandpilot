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
