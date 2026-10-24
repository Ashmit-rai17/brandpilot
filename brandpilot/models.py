"""Frozen data contracts. Change a field only after telling the other owner."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

HEX = r"^#[0-9A-Fa-f]{6}$"
Spacing = Literal["low", "medium", "high"]
Saturation = Literal["muted", "balanced", "vibrant"]


class Brief(BaseModel):
    company: Optional[str] = None
    product: Optional[str] = None
    audience: Optional[str] = None
    industry: Optional[str] = None
    positioning: Optional[str] = None
    personality: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    asset: str = "poster"
    headline: Optional[str] = None

    def missing(self) -> list[str]:
        return [f for f in ("company", "product", "audience", "headline") if not getattr(self, f)]

    def tags(self) -> set[str]:
        out = {t.lower() for t in self.personality}
        for f in (self.industry, self.positioning):
            if f:
                out.add(f.lower())
        return out


class Palette(BaseModel):
    background: str = Field(pattern=HEX)
    surface: str = Field(pattern=HEX)
    text: str = Field(pattern=HEX)
    primary: str = Field(pattern=HEX)
    accent: str = Field(pattern=HEX)


class TypeSpec(BaseModel):
    heading: str
    body: str
    scale: float = Field(ge=1.1, le=1.7)


class Motif(BaseModel):
    """The concrete, locked image direction selected from a style grammar."""
    subject: str
    composition: str
    lighting: str
    industry_hint: Optional[str] = None


class Direction(BaseModel):
    id: str
    style_id: str
    name: str
    rationale: str
    palette: Palette
    type: TypeSpec
    seed: Optional[int] = None
    variant: int = 0
    layout_template: Optional[str] = None
    motif: Optional[Motif] = None
    hue_family: Optional[str] = None


class DesignSystem(BaseModel):
    version: int = 1
    style_id: str
    style_name: str
    palette: Palette
    saturation: Saturation = "balanced"
    type: TypeSpec
    spacing: Spacing
    panel: Literal["none", "brutal", "glass"] = "none"
    image_style: str
    prompt_fragment: str
    negative: list[str]
    seed: Optional[int] = None
    variant: int = 0
    layout_template: Optional[str] = None
    motif: Optional[Motif] = None
    hue_family: Optional[str] = None
    locked: list[str] = Field(default_factory=lambda: ["type"])
    history: list[dict] = Field(default_factory=list)


class Patch(BaseModel):
    """Structured revision. Only these keys exist; anything else is rejected upstream."""
    saturation: Optional[Saturation] = None
    temperature: Optional[Literal["warmer", "cooler"]] = None
    spacing: Optional[Spacing] = None
    image_style: Optional[str] = Field(default=None, max_length=160)
    variation: bool = False
    wants_font_change: bool = False
    reason: str = ""

    @field_validator("image_style")
    @classmethod
    def strip(cls, v):
        return v.strip() if v else v

    def is_empty(self) -> bool:
        return not any([self.saturation, self.temperature, self.spacing, self.image_style, self.variation])


class CheckResult(BaseModel):
    name: str
    value: str
    threshold: str
    passed: bool
    note: str = ""


class AssetRecord(BaseModel):
    asset_type: Literal["poster", "social_post"]
    ds_version: int
    prompt: str
    background_path: str
    output_path: str
    checks: list[CheckResult]
    delivered_as: str = ""
