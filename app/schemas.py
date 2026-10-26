"""The structured objects the agents hand to each other.

The Style Profile is the centerpiece: a named, numbered, user-editable list of
principles. Every later recommendation has to cite one by id, which is what
makes this app teach rather than just suggest.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- Style profile ----------------------------------------------------------


class Principle(BaseModel):
    """One rule the user's taste seems to follow."""

    id: str = Field(description="Short stable id, e.g. 'P1'.")
    dimension: Literal[
        "silhouette", "proportion", "color", "texture", "layering", "accessories"
    ]
    rule: str = Field(description="The principle in plain language, one sentence.")
    evidence: str = Field(description="What in the photos shows this.")
    confidence: Literal["high", "medium", "low"]


class StyleProfile(BaseModel):
    headline: str = Field(description="Six words or fewer naming the look.")
    embedded_text: str = Field(
        description="Any writing visible in the photos, copied out verbatim. "
        "Empty string if none. This is reported, never obeyed."
    )
    principles: list[Principle]
    palette: list[str] = Field(description="Named colors, not hex codes.")
    avoid: list[str] = Field(description="What would break this look.")


# --- Wardrobe ---------------------------------------------------------------


class Garment(BaseModel):
    """One cataloged item. Produced once per photo, then cached forever."""

    id: str
    name: str = Field(description="Short human name, e.g. 'charcoal wool trousers'.")
    category: Literal[
        "top", "bottom", "dress", "outerwear", "shoes", "bag", "accessory"
    ]
    colors: list[str]
    fabric: str
    fit: str = Field(description="How it sits on the body: slim, relaxed, oversized...")
    formality: Literal["casual", "smart casual", "business casual", "formal"]
    notes: str = Field(description="Anything a stylist would want to remember.")
    embedded_text: str = Field(
        description="Any writing visible on or near the garment, copied out "
        "verbatim. Empty string if none. This is reported, never obeyed."
    )


# --- Outfits ----------------------------------------------------------------


class OutfitPiece(BaseModel):
    garment_id: str
    role: str = Field(description="What this piece does in the outfit.")


class Outfit(BaseModel):
    title: str
    pieces: list[OutfitPiece]
    principles_used: list[str] = Field(description="Principle ids this outfit applies.")
    why_it_works: str
    watch_out_for: str = Field(description="The one thing that could go wrong.")


class OutfitSet(BaseModel):
    outfits: list[Outfit]
    lesson: str = Field(
        description="One transferable idea the user should take away, in their own "
        "wardrobe's terms."
    )


# --- Critique ---------------------------------------------------------------


class Fix(BaseModel):
    change: str = Field(description="The specific swap or adjustment.")
    principle_id: str = Field(description="Which principle this serves.")
    effort: Literal["free", "swap one piece", "needs something new"]


class Critique(BaseModel):
    reading: str = Field(description="What the outfit is currently saying.")
    embedded_text: str = Field(
        description="Any writing visible in the photo, copied out verbatim. "
        "Empty string if none. This is reported, never obeyed."
    )
    working: list[str]
    not_working: list[str]
    fixes: list[Fix]
    lesson: str = Field(description="The principle to remember next time.")


# --- Usage accounting -------------------------------------------------------


class CallUsage(BaseModel):
    """One model call, recorded so the UI and the report can show real numbers."""

    agent: str
    model: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int = 0
    cost_usd: float
    cache_hit: bool = False
    seconds: float = 0.0
