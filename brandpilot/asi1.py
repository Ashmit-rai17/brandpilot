"""ASI1 API clients.

Chat:  POST https://api.asi1.ai/v1/chat/completions  (OpenAI-compatible, model "asi1")
Image: POST https://api.asi1.ai/v1/image/generate    (as in the official Image Generation Agent tutorial)
Both use  Authorization: Bearer $ASI1_API_KEY
"""
from __future__ import annotations

import base64
import json
import os
import re

import requests

BASE = os.getenv("ASI1_BASE_URL", "https://api.asi1.ai/v1")
CHAT_MODEL = os.getenv("ASI1_CHAT_MODEL", "asi1")
IMAGE_MODEL = os.getenv("ASI1_IMAGE_MODEL", "asi1")


class ASI1Error(RuntimeError):
    pass


def _key() -> str:
    key = os.getenv("ASI1_API_KEY") or os.getenv("ASI_LLM_KEY")
    if not key:
        raise ASI1Error("ASI1_API_KEY is not set")
    return key


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}


def chat(system: str, user: str, timeout: int = 45) -> str:
    payload = {"model": CHAT_MODEL, "temperature": 0.2,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = requests.post(f"{BASE}/chat/completions", json=payload, headers=_headers(), timeout=timeout)
    if not r.ok:
        raise ASI1Error(f"chat {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = text.replace("```json", "```")
    m = re.search(r"```(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def chat_json(system: str, user: str) -> dict:
    """One call, one retry with a stricter instruction. Raises on second failure."""
    reply = chat(system, user)
    try:
        return extract_json(reply)
    except ValueError:
        reply = chat(system + "\nReturn ONLY a single JSON object. No prose, no markdown.", user)
        return extract_json(reply)


def generate_image(prompt: str, timeout: int = 90) -> bytes:
    """Return PNG/JPEG bytes. One retry on failure."""
    last = None
    for _ in range(2):
        try:
            r = requests.post(f"{BASE}/image/generate", headers=_headers(), timeout=timeout,
                              json={"model": IMAGE_MODEL, "prompt": prompt, "size": os.getenv("ASI1_IMAGE_SIZE", "auto")})
            if not r.ok:
                raise ASI1Error(f"image {r.status_code}: {r.text[:300]}")
            return _image_bytes(r.json(), timeout)
        except (requests.RequestException, ASI1Error, ValueError) as e:
            last = e
    raise ASI1Error(f"image generation failed: {last}")


def _image_bytes(data: dict, timeout: int) -> bytes:
    """Handles the response shapes the official tutorial handles: url/image_url, images[].url, data[].url|b64_json."""
    candidates = [data.get("image_url"), data.get("url")]
    if isinstance(data.get("images"), list) and data["images"]:
        first = data["images"][0]
        candidates.append(first.get("url") if isinstance(first, dict) else first)
    if isinstance(data.get("data"), list) and data["data"]:
        first = data["data"][0]
        if isinstance(first, dict):
            if first.get("b64_json"):
                return base64.b64decode(first["b64_json"])
            candidates.append(first.get("url"))
    for c in candidates:
        if not isinstance(c, str) or not c:
            continue
        if c.startswith("data:image/"):
            return base64.b64decode(c.split(",", 1)[1])
        if c.startswith("http"):
            img = requests.get(c, timeout=timeout)
            img.raise_for_status()
            return img.content
    raise ValueError(f"no image in response; keys={list(data)}")


def compile_prompt(ds, asset_type: str) -> str:
    """Deterministic template. The LLM never paraphrases the design system."""
    pal = ds.palette
    shape = "vertical 4:5 poster background" if asset_type == "poster" else "square 1:1 social post background"
    from .kb import styles
    template = next((x for x in styles()[ds.style_id]["grammar"]["layout_templates"]
                     if x["id"] == ds.layout_template), None)
    copy_space = (template or {}).get("copy_space", "top")
    motif = ds.motif
    motif_instruction = ""
    if motif:
        hint = f", {motif.industry_hint}" if motif.industry_hint else ""
        motif_instruction = f" Locked motif: {motif.subject}, {motif.composition}, {motif.lighting}{hint}."
    return (
        f"{shape}. {ds.prompt_fragment}. Image style: {ds.image_style}.{motif_instruction} "
        f"Color palette strictly limited to {pal.background}, {pal.surface}, {pal.primary} and {pal.accent}. "
        f"Keep the {copy_space} calm and uncluttered with plenty of negative space for copy. "
        f"Absolutely no text, no letters, no words, no numbers, no logos, no watermarks. "
        f"Avoid: {', '.join(ds.negative)}."
    )
