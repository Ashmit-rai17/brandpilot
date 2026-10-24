"""Connect a running local agent's mailbox without the browser inspector.

python -m spikes.connect_mailbox 8011   # Spike A
python -m spikes.connect_mailbox 8010   # agent.py

Sends what the inspector's Connect button sends: POST /connect with an AgentverseConnectRequest
(uagents/mailbox.py, route in uagents/agent.py). The Agentverse API key is the user_token, as in
uagents_core/utils/registration.py. Prints only the status and the response body; never the key.
"""
import sys, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # project root, so `python spikes/x.py` works
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("AGENTVERSE_API_KEY")
assert key, "AGENTVERSE_API_KEY missing in .env"
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8011

r = requests.post(f"http://127.0.0.1:{port}/connect", json={"user_token": key, "agent_type": "mailbox"}, timeout=60)
body = r.text.replace(key, "***")
body = re.sub(r"(eyJ|av-|sk-)[A-Za-z0-9._-]{8,}", "***", body)  # mask anything token-like
print("status", r.status_code)
print(body)
