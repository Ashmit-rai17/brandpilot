"""Schema check for the knowledge files (Prashant's acceptance test). python -m tests.validate_knowledge"""
import json
from pathlib import Path

from brandpilot.kb import KNOWLEDGE, contrast, font_path
from brandpilot.models import Palette, TypeSpec

REQUIRED = {"id", "name", "summary", "use_when", "avoid_when", "palette", "type", "spacing", "panel",
            "image_style", "prompt_fragment", "negative", "grammar"}
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
    g = s["grammar"]
    rules = g.get("palette", {})
    for key in ("background_lightness", "background_saturation", "text_lightness", "primary_saturation", "accent_saturation"):
        value = rules.get(key)
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(n, (int, float)) and 0 <= n <= 100 for n in value) or value[0] > value[1]:
            errors.append(f"{s['id']}: invalid palette {key}")
    allowed_schemes = {"analogous", "complementary", "split-complementary", "monochrome"}
    if not rules.get("harmony_schemes") or set(rules["harmony_schemes"]) - allowed_schemes:
        errors.append(f"{s['id']}: invalid harmony schemes")
    from brandpilot.variation import HUE_FAMILY_RANGES
    if not rules.get("hue_families") or set(rules["hue_families"]) - set(HUE_FAMILY_RANGES):
        errors.append(f"{s['id']}: invalid hue families")
    pairs = g.get("font_pairings", [])
    if not 2 <= len(pairs) <= 3:
        errors.append(f"{s['id']}: needs 2-3 font pairings")
    classes = set(g.get("heading_classes", []))
    if not classes:
        errors.append(f"{s['id']}: heading_classes missing")
    for pair in pairs:
        try:
            spec = TypeSpec(**pair["type"])
            heading = spec.heading
            if heading not in fonts or not font_path(heading).exists():
                errors.append(f"{s['id']}: pairing font {heading} unavailable")
            elif json.loads((KNOWLEDGE / "typography.json").read_text())["fonts"] and next(f for f in json.loads((KNOWLEDGE / "typography.json").read_text())["fonts"] if f["id"] == heading)["class"] not in classes:
                errors.append(f"{s['id']}: heading pairing breaks heading_classes")
        except (KeyError, ValueError):
            errors.append(f"{s['id']}: invalid font pairing")
    templates = g.get("layout_templates", [])
    if len(templates) != 3:
        errors.append(f"{s['id']}: needs exactly 3 layout templates")
    for template in templates:
        if not {"id", "text_anchor", "image_anchor", "copy_space", "text_align", "panel"} <= set(template):
            errors.append(f"{s['id']}: malformed layout template")
        for key, value in g.get("layout_invariants", {}).items():
            if template.get(key) != value:
                errors.append(f"{s['id']}: template {template.get('id')} breaks {key} invariant")
    motif = g.get("image_motifs", {})
    if not all(motif.get(k) for k in ("subjects", "compositions", "lighting")):
        errors.append(f"{s['id']}: motif pools must be non-empty")
    if set(motif.get("industry_hints", {})) - set(data["tag_vocabulary"]["industry"]):
        errors.append(f"{s['id']}: invalid industry motif hint")
refs = KNOWLEDGE / "references.json"
if refs.exists():
    for r in json.loads(refs.read_text())["references"]:
        for k in ("id", "name", "url", "style_id", "verified_on"):
            if k not in r:
                errors.append(f"reference {r.get('id')}: missing {k}")
print("OK" if not errors else "\n".join(errors))
raise SystemExit(1 if errors else 0)
