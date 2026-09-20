"""Strict Pydantic contract for LLM extraction output.

Every item carries the source_url it was found on; provenance is per-contact,
not per-run. Unknown extra keys are rejected so schema drift fails loud (D-008).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SocialPlatform = Literal[
    "facebook", "instagram", "twitter", "x", "youtube", "tiktok", "whatsapp", "linkedin"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContactItem(_Strict):
    value: str
    source_url: str


class SocialItem(_Strict):
    platform: SocialPlatform
    value: str
    source_url: str


class RawContextItem(_Strict):
    text: str
    source_url: str


class ExtractionResult(_Strict):
    emails: list[ContactItem] = Field(default_factory=list)
    phones: list[ContactItem] = Field(default_factory=list)
    socials: list[SocialItem] = Field(default_factory=list)
    contact_forms: list[ContactItem] = Field(default_factory=list)
    raw_context: list[RawContextItem] = Field(default_factory=list)
