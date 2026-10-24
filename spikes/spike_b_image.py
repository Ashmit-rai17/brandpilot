"""SPIKE B (gate): ASI1 image generation -> local file -> (optional) Agentverse storage upload.

python -m spikes.spike_b_image             # generate + save data/spike_b.png, print response shape
python -m spikes.spike_b_image --upload    # also upload to Agentverse ExternalStorage (needs AGENTVERSE_API_KEY)
PASS = file opens locally. Display in ASI:One is verified by running agent.py and approving a design system.
"""
import sys, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # project root, so `python spikes/x.py` works
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("ASI1_API_KEY")
assert key, "ASI1_API_KEY missing in .env"
t = time.time()
r = requests.post("https://api.asi1.ai/v1/image/generate", timeout=120,
                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                  json={"model": "asi1", "prompt": "abstract soft indigo glow on a near-black background, no text",
                        "size": "auto"})
print("status", r.status_code, f"{time.time() - t:.1f}s")
data = r.json()
print("top-level keys:", list(data))  # shape only, never the key
from brandpilot.asi1 import _image_bytes  # noqa: E402
png = _image_bytes(data, 60)
os.makedirs("data", exist_ok=True)
open("data/spike_b.png", "wb").write(png)
print("saved data/spike_b.png", len(png), "bytes")

if "--upload" in sys.argv:
    from uagents_core.storage import ExternalStorage
    st = ExternalStorage(api_token=os.environ["AGENTVERSE_API_KEY"],
                         storage_url=os.getenv("AGENTVERSE_URL", "https://agentverse.ai") + "/v1/storage")
    print("asset id:", st.create_asset(name="spike_b", content=png, mime_type="image/png"))
