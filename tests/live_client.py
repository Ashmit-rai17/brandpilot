"""Live test client: a second mailbox uAgent that chats with BrandPilot through Agentverse.

Tests the real mailbox path (not the ASI:One UI). Not collected by pytest.

python -m tests.live_client serve                      # run the client agent (port CLIENT_PORT, default 8012)
python -m spikes.connect_mailbox 8012                  # once, to connect its mailbox
python -m tests.live_client send <agent_address> "<text>" [--wait 180] [--quiet 10]

`send` asks the running client (POST /send) to send a ChatMessage, then waits until replies stop
arriving for --quiet seconds (or --wait elapses), and prints each reply and the elapsed time.
Replies are appended to data/live_client/replies.jsonl; posters arriving as ResourceContent are
downloaded with the client's own identity into data/live_client/.
"""
import sys, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # project root
import argparse
import base64
import json
import os
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4

OUT = pathlib.Path("data/live_client")
LOG = OUT / "replies.jsonl"
PORT = int(os.getenv("CLIENT_PORT", "8012"))


def serve():
    from dotenv import load_dotenv
    from uagents import Agent, Context, Model, Protocol
    from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, EndSessionContent,
                                                     MetadataContent, ResourceContent, StartSessionContent,
                                                     TextContent, chat_protocol_spec)
    from uagents_core.storage import ExternalStorage

    load_dotenv()
    OUT.mkdir(parents=True, exist_ok=True)
    agent = Agent(name="BrandPilot test client", seed=(os.getenv("AGENT_SEED") or secrets.token_hex(16)) + "-client",
                  port=PORT, mailbox=True, publish_agent_details=True)
    proto = Protocol(spec=chat_protocol_spec)

    class SendRequest(Model):
        to: str
        text: str
        start_session: bool = False

    class SendResponse(Model):
        ok: bool
        msg_id: str

    def record(entry: dict):
        entry["t"] = time.time()
        with LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def download(asset_id: str) -> str:
        data = ExternalStorage(identity=agent._identity).download(str(asset_id))
        raw = data.get("contents") if isinstance(data, dict) else None
        if not raw:
            return f"download returned keys {list(data) if isinstance(data, dict) else type(data).__name__}"
        path = OUT / f"{asset_id}.png"
        path.write_bytes(base64.b64decode(raw))
        return str(path)

    @agent.on_rest_post("/send", SendRequest, SendResponse)
    async def send(ctx: Context, req: SendRequest) -> SendResponse:
        content = ([StartSessionContent(type="start-session")] if req.start_session else []) + [
            TextContent(type="text", text=req.text)]
        msg = ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)
        await ctx.send(req.to, msg)
        record({"dir": "out", "to": req.to, "text": req.text, "msg_id": str(msg.msg_id)})
        ctx.logger.info(f"SENT {req.text[:120]!r}")
        return SendResponse(ok=True, msg_id=str(msg.msg_id))

    @proto.on_message(ChatMessage)
    async def on_msg(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        for c in msg.content:
            if isinstance(c, TextContent):
                record({"dir": "in", "kind": "text", "text": c.text})
            elif isinstance(c, MetadataContent):
                md = dict(c.metadata)
                record({"dir": "in", "kind": "metadata", "card_kind": md.get("card_kind"),
                        "card_payload": md.get("card_payload"), "keys": sorted(md)})
            elif isinstance(c, ResourceContent):
                res = c.resource if not isinstance(c.resource, list) else c.resource[0]
                try:
                    saved = download(str(c.resource_id))
                except Exception as e:  # report, never crash the client
                    saved = f"download failed: {e}"
                record({"dir": "in", "kind": "resource", "resource_id": str(c.resource_id), "uri": res.uri,
                        "metadata": res.metadata, "saved": saved})
            elif isinstance(c, EndSessionContent):
                record({"dir": "in", "kind": "end-session"})
            else:
                record({"dir": "in", "kind": type(c).__name__})
        ctx.logger.info(f"RECEIVED {[type(c).__name__ for c in msg.content]} from {sender[:16]}...")

    @proto.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        record({"dir": "in", "kind": "ack", "acknowledged": str(msg.acknowledged_msg_id)})

    agent.include(proto, publish_manifest=True)
    print(f"test client address: {agent.address}  port={PORT}")
    agent.run()


def send(to: str, text: str, wait: float, quiet: float, start_session: bool):
    import requests

    OUT.mkdir(parents=True, exist_ok=True)
    start = LOG.stat().st_size if LOG.exists() else 0
    t0 = time.time()
    r = requests.post(f"http://127.0.0.1:{PORT}/send", json={"to": to, "text": text, "start_session": start_session},
                      timeout=30)
    print(f">>> {text!r}  (status {r.status_code})")
    last_reply = None
    seen = 0
    while time.time() - t0 < wait:
        time.sleep(1)
        lines = LOG.read_text()[start:].splitlines() if LOG.exists() else []
        replies = [json.loads(x) for x in lines if x.strip()]
        replies = [e for e in replies if e["dir"] == "in"]
        for e in replies[seen:]:
            dt = e["t"] - t0
            if e["kind"] == "text":
                print(f"  +{dt:5.1f}s TEXT: {e['text'][:400]!r}")
            elif e["kind"] == "metadata":
                print(f"  +{dt:5.1f}s CARD {e['card_kind']}: {str(e['card_payload'])[:300]}")
            elif e["kind"] == "resource":
                print(f"  +{dt:5.1f}s RESOURCE {e['resource_id']} uri={e['uri'][:90]} meta={e['metadata']} saved={e['saved']}")
            else:
                print(f"  +{dt:5.1f}s {e['kind'].upper()}")
            if e["kind"] != "ack":
                last_reply = e["t"]
        seen = len(replies)
        if last_reply and time.time() - last_reply > quiet:
            break
    if last_reply:
        print(f"<<< last reply at +{last_reply - t0:.1f}s")
    else:
        print(f"<<< NO REPLY within {wait:.0f}s")
        sys.exit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    s = sub.add_parser("send")
    s.add_argument("to")
    s.add_argument("text")
    s.add_argument("--wait", type=float, default=180)
    s.add_argument("--quiet", type=float, default=10)
    s.add_argument("--start-session", action="store_true")
    a = p.parse_args()
    serve() if a.cmd == "serve" else send(a.to, a.text, a.wait, a.quiet, a.start_session)
