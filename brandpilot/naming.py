"""Naming helpers (no network, no agent imports)."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def asset_name(name: str) -> str:
    """Unique, readable storage asset name: poster_v1.png -> poster_v1-1a2b3c4d.png."""
    p = Path(name)
    return f"{p.stem}-{uuid4().hex[:8]}{p.suffix}"
