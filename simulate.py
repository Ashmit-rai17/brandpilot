"""Run the full BrandPilot flow in the terminal, without ASI:One.

python simulate.py            # real ASI1 calls (needs ASI1_API_KEY)
python simulate.py --offline  # deterministic fallbacks + placeholder backgrounds
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
from brandpilot.asi1 import generate_image  # noqa: E402
from brandpilot.brain import Brain  # noqa: E402
from brandpilot.flow import Services, handle, new_session  # noqa: E402
from tests.fakes import placeholder_background  # noqa: E402

offline = "--offline" in sys.argv
svc = Services(brain=Brain(offline=offline), generate_image=placeholder_background if offline else generate_image,
               data_dir=Path("data"))
session = new_session()
print("BrandPilot simulator. Type JSON to simulate a card click. Ctrl+C to quit.\n")
for r in handle(session, "hi", svc):
    print("BOT:", r.text, f"\n[card {r.card_kind}]" if r.card_kind else "")
while True:
    try:
        text = input("\nYOU: ")
    except (EOFError, KeyboardInterrupt):
        break
    for r in handle(session, text, svc):
        print("\nBOT:", r.text)
        if r.card_kind:
            print(f"[card {r.card_kind}] {json.dumps(r.card_payload)[:300]}")
        if r.image_png:
            print(f"[image saved: data/sessions/{session.get('sid')}/{r.image_name}]")
