"""BrandPilot uAgent: Agent Chat Protocol over an Agentverse mailbox, usable from ASI:One.

Run:  python agent.py   then open the inspector URL from the logs, click Connect, choose Mailbox.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import requests
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, MetadataContent, Resource,
    ResourceContent, StartSessionContent, TextContent, chat_protocol_spec,
)

load_dotenv()

from brandpilot.asi1 import generate_image  # noqa: E402
from brandpilot.brain import Brain  # noqa: E402
from brandpilot.cards import parse_selection  # noqa: E402
from brandpilot.naming import asset_name  # noqa: E402
from brandpilot.flow import Reply, Services, handle, is_long_action, new_session  # noqa: E402

logging.basicConfig(level=logging.INFO)
SEED = os.getenv("AGENT_SEED") or secrets.token_hex(16)
NAME = os.getenv("AGENT_NAME", "BrandPilot")
DELIVERY = os.getenv("IMAGE_DELIVERY", "resource")  # resource | url | github
GITHUB_REPO = os.getenv("GITHUB_REPO", "Ashmit-rai17/brandpilot")
GITHUB_BRANCH = "assets"  # posters only; main is never written
AGENTVERSE_URL = os.getenv("AGENTVERSE_URL", "https://agentverse.ai")

agent = Agent(name=NAME, seed=SEED, port=int(os.getenv("AGENT_PORT", "8000")),
              mailbox=True, publish_agent_details=True)
chat_proto = Protocol(spec=chat_protocol_spec)
services = Services(brain=Brain(offline=os.getenv("BRANDPILOT_OFFLINE") == "1"),
                    generate_image=generate_image, data_dir=Path(os.getenv("DATA_DIR", "data")))


def _ts() -> str:
    """UTC wall-clock timestamp for diagnostic log lines."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _chat_session(msg: ChatMessage) -> tuple[bool, str | None]:
    """(has StartSessionContent, ASI:One chat id from the 'x-session-id' metadata if present)."""
    start = any(isinstance(c, StartSessionContent) for c in msg.content)
    chat_id = next((c.metadata["x-session-id"] for c in msg.content
                    if isinstance(c, MetadataContent) and c.metadata.get("x-session-id")), None)
    return start, chat_id


def _ignore_reason(msg: ChatMessage, text: str) -> str | None:
    """Messages that are not user input. Seen live: ASI:One streams its own assistant reply to us as
    [TextContent, MetadataContent{"index": ...}] chunks followed by bare EndStreamContent."""
    if any(isinstance(c, MetadataContent) and "index" in c.metadata for c in msg.content):
        return "ASI:One stream chunk ignored"
    if not text and not any(isinstance(c, StartSessionContent) for c in msg.content):
        return "message without text ignored"
    return None


def _is_new_chat(session: dict, start: bool, chat_id: str | None) -> bool:
    """A new ASI:One chat starts a fresh design session; repeated StartSession for the same chat id does not."""
    return start and (chat_id is None or chat_id != session.get("chat_session"))


DUP_WINDOW_S = 120
_seen_ids: dict[str, set] = {}
_recent_text: dict[str, dict[str, float]] = {}
_REPEATABLE = re.compile(r"^\s*(?:@\S+\s*)?(?:restart|start over|new brand|reset|retry|try again|regenerate)\b", re.I)


def _duplicate(sender: str, msg_id: str, text: str, now: float) -> str | None:
    """Why this message should be skipped (repeated msg_id, or identical text within DUP_WINDOW_S), else None."""
    ids = _seen_ids.setdefault(sender, set())
    if msg_id in ids:
        return "duplicate msg_id skipped"
    ids.add(msg_id)
    recent = _recent_text.setdefault(sender, {})
    for t in [t for t, at in recent.items() if now - at > DUP_WINDOW_S]:
        del recent[t]
    if text and not _REPEATABLE.match(text):  # 'retry'/'restart' must always go through
        if text in recent:
            return "duplicate text skipped"
        recent[text] = now
    return None


def _msg(content, end: bool = False) -> ChatMessage:
    if end:
        content = list(content) + [EndSessionContent(type="end-session")]
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def _host_resource(png: bytes, name: str, recipient: str):
    """Agentverse ExternalStorage + ResourceContent (pattern from the official payment image example)."""
    from uagents_core.storage import ExternalStorage
    key = os.getenv("AGENTVERSE_API_KEY")
    if not key:
        raise RuntimeError("AGENTVERSE_API_KEY not set")
    storage = ExternalStorage(api_token=key, storage_url=f"{AGENTVERSE_URL}/v1/storage")
    asset_id = storage.create_asset(name=asset_name(name), content=png, mime_type="image/png")
    storage.set_permissions(asset_id=asset_id, agent_address=recipient)
    uri = f"agent-storage://{storage.storage_url}/{asset_id}"
    return ResourceContent(type="resource", resource_id=UUID(str(asset_id)),
                           resource=Resource(uri=uri, metadata={"mime_type": "image/png", "role": "generated-image"}))


def _host_url(png: bytes, name: str) -> str:
    """Fallback: public https link (tmpfiles.org is ephemeral; fine for testing, not for judging)."""
    r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": (name, png, "image/png")}, timeout=60)
    r.raise_for_status()
    url = r.json()["data"]["url"]
    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1).replace("http://", "https://", 1)


def _host_github(png: bytes, name: str) -> str:
    """Public raw.githubusercontent.com link: commit the PNG to the 'assets' branch via the contents API."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    api = f"https://api.github.com/repos/{GITHUB_REPO}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    r = requests.get(f"{api}/git/ref/heads/{GITHUB_BRANCH}", headers=headers, timeout=30)
    if r.status_code == 404:  # create the branch from main's head; main itself is untouched
        main = requests.get(f"{api}/git/ref/heads/main", headers=headers, timeout=30)
        main.raise_for_status()
        r = requests.post(f"{api}/git/refs", headers=headers, timeout=30,
                          json={"ref": f"refs/heads/{GITHUB_BRANCH}", "sha": main.json()["object"]["sha"]})
    if r.status_code >= 400:
        raise RuntimeError(f"branch {GITHUB_BRANCH}: HTTP {r.status_code} {r.text[:200]}")
    path = f"posters/{asset_name(name)}"
    r = requests.put(f"{api}/contents/{path}", headers=headers, timeout=60,
                     json={"message": f"poster {path}", "branch": GITHUB_BRANCH,
                           "content": base64.b64encode(png).decode()})
    if r.status_code >= 400:
        raise RuntimeError(f"upload {path}: HTTP {r.status_code} {r.text[:200]}")
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{path}"


def _with_image(text: str, name: str, url: str) -> str:
    """Poster markdown inside the same message as its text and suggestions card, so ASI:One can never show the
    recommendations without the picture (live: a separate image-only message was dropped by a webhook 504)."""
    return f"![{name}]({url})\n\n{text}"


async def _send(ctx: Context, to: str, reply: Reply):
    if reply.image_png:
        try:
            if DELIVERY == "resource":
                t = time.time()
                res = await asyncio.to_thread(_host_resource, reply.image_png, reply.image_name, to)
                ctx.logger.info(f"OUT image uploaded asset={res.resource_id} bytes={len(reply.image_png)} "
                                f"in {time.time() - t:.1f}s")
                await ctx.send(to, _msg([res]))
                ctx.logger.info("OUT ResourceContent sent")
            elif DELIVERY == "github":
                t = time.time()
                try:
                    url = await asyncio.to_thread(_host_github, reply.image_png, reply.image_name)
                except Exception as e:  # fall back to url mode for this message
                    ctx.logger.warning(f"github delivery failed, falling back to url: {e}")
                    url = await asyncio.to_thread(_host_url, reply.image_png, reply.image_name)
                ctx.logger.info(f"OUT image url {url} bytes={len(reply.image_png)} upload={time.time() - t:.1f}s")
                reply.text = _with_image(reply.text, reply.image_name, url)
            else:
                url = await asyncio.to_thread(_host_url, reply.image_png, reply.image_name)
                ctx.logger.info(f"OUT image url {url}")
                reply.text = _with_image(reply.text, reply.image_name, url)
        except Exception as e:
            ctx.logger.error(f"image delivery failed: {e}")
            reply.text = f"(Image delivery failed: {e}. The file is saved locally.)\n\n" + reply.text
    content = [TextContent(type="text", text=reply.text)]
    if reply.card_kind:
        content.append(MetadataContent(type="metadata", metadata={
            "card_protocol_version": "1", "requires_card_interaction": "true",
            "card_kind": reply.card_kind, "card_payload": json.dumps(reply.card_payload),
            "preferred_drawer_width_px": "540"}))
    await ctx.send(to, _msg(content, end=reply.end_session))
    ctx.logger.info(f"OUT text ({len(reply.text)} chars) card={reply.card_kind} end={reply.end_session} "
                    f"sent_at={_ts()}: {reply.text[:160]!r}")


@chat_proto.on_message(ChatMessage)
async def on_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    text = "\n".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    ctx.logger.info(f"IN types={[type(c).__name__ for c in msg.content]} text={text[:600]!r} "
                    f"msg_id={msg.msg_id} sender={sender[:16]} ctx_session={ctx.session} at={_ts()}")
    for c in msg.content:
        if isinstance(c, MetadataContent):
            ctx.logger.info(f"IN metadata={json.dumps(c.metadata)[:600]}")
    ignored = _ignore_reason(msg, text)
    if ignored:
        ctx.logger.info(f"{ignored}: msg_id={msg.msg_id} sender={sender[:16]}")
        return
    dup = _duplicate(sender, str(msg.msg_id), text, time.time())
    if dup:
        ctx.logger.info(f"{dup}: msg_id={msg.msg_id} sender={sender[:16]} text={text[:80]!r}")
        return
    key = f"session:{sender}"  # one design session per ASI:One user, as in the official cards example
    session = ctx.storage.get(key) or new_session()
    start, chat_id = _chat_session(msg)
    if _is_new_chat(session, start, chat_id):
        ctx.logger.info(f"SESSION fresh: new chat {chat_id} (was {session.get('chat_session')}, stage {session['stage']})")
        session = new_session()
    if chat_id:
        session["chat_session"] = chat_id
    if not text and start:
        ctx.storage.set(key, session)
        return
    if is_long_action(session, text):
        await ctx.send(sender, _msg([TextContent(type="text", text="Working on it, about 15 to 20 seconds.")]))
        ctx.logger.info(f"OUT working notice sent_at={_ts()}")
    stage, t = session["stage"], time.time()
    handle_start = _ts()
    replies = await asyncio.to_thread(handle, session, text, services)
    ctx.logger.info(f"FLOW {stage} -> {session['stage']} sel={parse_selection(text)} handled in {time.time() - t:.1f}s llm={services.brain.last_source} "
                    f"msg_id={msg.msg_id} handle_start={handle_start} handle_end={_ts()}")
    ctx.storage.set(key, session)  # saved before sending, so a delivery error never loses state
    for r in replies:
        await _send(ctx, sender, r)


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    print(f"BrandPilot address: {agent.address}  (delivery={DELIVERY})")
    agent.run()
