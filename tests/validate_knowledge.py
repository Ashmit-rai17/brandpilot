"""Schema check for the knowledge files (Prashant's acceptance test). python -m tests.validate_knowledge"""
import json
from pathlib import Path

from brandpilot.kb import KNOWLEDGE, contrast, font_path
from brandpilot.models import Palette, TypeSpec

REQUIRED = {"id", "name", "summary", "use_when", "avoid_when", "palette", "type", "spacing", "panel",
            "image_style", "prompt_fragment", "negative"}
data = json.loads((KNOWLEDGE / "styles.json").read_text())
fonts = {f["id"] for f in json.loads((KNOWLEDGE / "typography.json").read_text())["fonts"]}
vocab = set(data["tag_vocabulary"]["industry"]) | set(data["tag_vocabulary"]["personality"])
errors = []
for s in data["styles"]:
    if missing := REQUIRED - set(s):
        errors.append(f"{s.get('id')}: missing {missing}")
        continue
    Palette(**s["palette"]), TypeSpec(**s["type"])
    for role in ("heading", "body"):
        if s["type"][role] not in fonts or not font_path(s["type"][role]).exists():
            errors.append(f"{s['id']}: font {s['type'][role]} not available locally")
    if bad := (set(s["use_when"]) | set(s["avoid_when"])) - vocab:
        errors.append(f"{s['id']}: tags not in vocabulary {bad}")
    if contrast(s["palette"]["text"], s["palette"]["background"]) < 4.5:
        errors.append(f"{s['id']}: text/background contrast below 4.5:1")
refs = KNOWLEDGE / "references.json"
if refs.exists():
    for r in json.loads(refs.read_text())["references"]:
        for k in ("id", "name", "url", "style_id", "verified_on"):
            if k not in r:
                errors.append(f"reference {r.get('id')}: missing {k}")
print("OK" if not errors else "\n".join(errors))
raise SystemExit(1 if errors else 0)
