"""SPIKE A (gate): smallest ASI:One-compatible agent. Echoes text back over the Agent Chat Protocol.

1. python -m spikes.spike_a_hello   (or: python spikes/spike_a_hello.py)
2. Open the 'Agent inspector available at' URL in the logs -> Connect -> Mailbox.
3. agentverse.ai -> Agents -> this agent -> Chat with Agent (opens ASI:One). Send "hello".
PASS = the echo reply appears in ASI:One. Copy the agent address into README.md.
"""
import sys, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # project root, so `python spikes/x.py` works
import os
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, TextContent,
                                                 chat_protocol_spec)

load_dotenv()
agent = Agent(name=os.getenv("AGENT_NAME", "BrandPilot") + " spike", seed=(os.getenv("AGENT_SEED") or secrets.token_hex(16)) + "-spike",
              port=8001, mailbox=True, publish_agent_details=True)
proto = Protocol(spec=chat_protocol_spec)


@proto.on_message(ChatMessage)
async def on_msg(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent))
    ctx.logger.info(f"from {sender}: {text!r}")
    await ctx.send(sender, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                       content=[TextContent(type="text", text=f"BrandPilot spike received: {text}")]))


@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(proto, publish_manifest=True)
if __name__ == "__main__":
    print("address:", agent.address)
    agent.run()
