"""BrandPilot uAgent: Agent Chat Protocol over an Agentverse mailbox, usable from ASI:One.

Run:  python agent.py   then open the inspector URL from the logs, click Connect, choose Mailbox.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
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
from brandpilot.flow import Reply, Services, handle, new_session  # noqa: E402

logging.basicConfig(level=logging.INFO)
SEED = os.getenv("AGENT_SEED") or secrets.token_hex(16)
NAME = os.getenv("AGENT_NAME", "BrandPilot")
DELIVERY = os.getenv("IMAGE_DELIVERY", "resource")  # resource | url
AGENTVERSE_URL = os.getenv("AGENTVERSE_URL", "https://agentverse.ai")

agent = Agent(name=NAME, seed=SEED, port=int(os.getenv("AGENT_PORT", "8000")),
              mailbox=True, publish_agent_details=True)
chat_proto = Protocol(spec=chat_protocol_spec)
services = Services(brain=Brain(offline=os.getenv("BRANDPILOT_OFFLINE") == "1"),
                    generate_image=generate_image, data_dir=Path(os.getenv("DATA_DIR", "data")))


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
            else:
                url = await asyncio.to_thread(_host_url, reply.image_png, reply.image_name)
                ctx.logger.info(f"OUT image url {url}")
                await ctx.send(to, _msg([TextContent(type="text", text=f"![{reply.image_name}]({url})")]))
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
    ctx.logger.info(f"OUT text ({len(reply.text)} chars) card={reply.card_kind} end={reply.end_session}: "
                    f"{reply.text[:160]!r}")


@chat_proto.on_message(ChatMessage)
async def on_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    text = "\n".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    ctx.logger.info(f"IN types={[type(c).__name__ for c in msg.content]} text={text[:600]!r}")
    for c in msg.content:
        if isinstance(c, MetadataContent):
            ctx.logger.info(f"IN metadata={json.dumps(c.metadata)[:600]}")
    if not text and any(isinstance(c, StartSessionContent) for c in msg.content):
        return
    key = f"session:{sender}"  # one design session per ASI:One user, as in the official cards example
    session = ctx.storage.get(key) or new_session()
    stage, t = session["stage"], time.time()
    replies = await asyncio.to_thread(handle, session, text, services)
    ctx.logger.info(f"FLOW {stage} -> {session['stage']} sel={parse_selection(text)} handled in {time.time() - t:.1f}s llm={services.brain.last_source}")
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
