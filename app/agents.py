"""The four agents.

    Cataloger  photo of an item      -> Garment        (once per item, cached)
    Analyst    inspiration photos    -> StyleProfile   (the teaching artifact)
    Stylist    profile + wardrobe    -> OutfitSet      (text only, cheap)
    Critic     outfit photo + profile-> Critique

Only the Cataloger, Analyst and Critic look at pixels. The Stylist reads the
catalog the Cataloger already wrote, which is why adding an outfit costs
cents rather than dollars.
"""

from __future__ import annotations

import json

from llm import call
from safety import GUARDRAIL_CLAUSE
from schemas import Critique, Garment, OutfitSet, StyleProfile

VOICE = """
You are a patient styling teacher. Your user wants to understand their own taste
well enough to buy less and wear more of what they already own, and to feel
comfortable in it. They are smart and do not want to be talked down to.

Explain the reasoning, not just the verdict, and name the principle at work so
they can apply it themselves next time — standing in a store as much as standing
in their closet. Favor what they already have over anything new. Be specific and
concrete. Never use filler praise.
""".strip()


def _sys(role: str) -> str:
    return f"{VOICE}\n\n{role}\n\n{GUARDRAIL_CLAUSE}"


# --- Cataloger --------------------------------------------------------------

CATALOGER = _sys("""
Catalog one garment from a photo. Describe only what you can see: category,
colors, fabric, how it is cut, how formal it reads. Keep `name` short enough to
sit in a list. If several items appear, describe the one in the foreground.
""".strip())


def catalog(image_url: str, item_id: str):
    parts = [
        {"type": "input_text", "text": f"Catalog this garment. Use id {item_id}."},
        {"type": "input_image", "image_url": image_url},
    ]
    return call("cataloger", CATALOGER, parts, Garment, max_output_tokens=1200)


# --- Analyst ----------------------------------------------------------------

ANALYST = _sys("""
Read a set of inspiration photos and work out the styling logic they share.

Write 4 to 7 principles. A principle is a rule the user could apply tomorrow to
clothes they already own, so "volume on top balanced by a narrow leg" is useful
and "wears nice clothes" is not. Cover different dimensions; do not write four
principles about color. Mark a principle `low` confidence when only one photo
supports it. In `evidence`, point at what in the photos shows it.
""".strip())


def analyze(image_urls: list[str], note: str = ""):
    parts: list[dict] = [{
        "type": "input_text",
        "text": (
            "Find the styling logic these photos share."
            + (f"\n\nThe user adds: {note}" if note else "")
        ),
    }]
    for url in image_urls:
        parts.append({"type": "input_image", "image_url": url})
    return call("analyst", ANALYST, parts, StyleProfile, max_output_tokens=2500)


# --- Stylist ----------------------------------------------------------------

STYLIST = _sys("""
Build outfits from the user's own wardrobe that apply their style profile.

Rules:
- Use only garment ids from the catalog given. Never invent an item.
- Every outfit cites the principle ids it applies, in `principles_used`.
- Propose 3 outfits. Make them genuinely different from each other, not three
  versions of one idea.
- `why_it_works` explains the reasoning in terms of the principles.
- `watch_out_for` names the one way this outfit could go wrong.
- `lesson` is the transferable idea, phrased for this person's wardrobe, and
  should help them judge a future purchase, not just today's outfit.
If the wardrobe cannot support a principle, say so in `lesson` rather than
pretending it can.
""".strip())


def style(profile: StyleProfile, wardrobe: list[Garment], occasion: str = ""):
    payload = {
        "profile": profile.model_dump(exclude={"embedded_text"}),
        "wardrobe": [g.model_dump(exclude={"embedded_text"}) for g in wardrobe],
        "occasion": occasion or "no particular occasion",
    }
    parts = [{
        "type": "input_text",
        "text": "Build outfits from this wardrobe.\n\n" + json.dumps(payload),
    }]
    return call("stylist", STYLIST, parts, OutfitSet, max_output_tokens=2500)


# --- Critic -----------------------------------------------------------------

CRITIC = _sys("""
Diagnose an assembled outfit against the user's own style profile.

Be honest and specific. `working` and `not_working` are about the clothes and
how they sit together: proportion, line, color, texture, formality. Give 2 to 4
fixes, each tied to a principle id, and prefer fixes the user can make with what
they already own. If the outfit is good, say so plainly and give one refinement
rather than inventing problems.
""".strip())


def critique(image_url: str, profile: StyleProfile, complaint: str = "",
             wardrobe: list[Garment] | None = None):
    context = {
        "profile": profile.model_dump(exclude={"embedded_text"}),
        "wardrobe": [g.model_dump(exclude={"embedded_text"}) for g in (wardrobe or [])],
    }
    parts = [
        {
            "type": "input_text",
            "text": (
                "Diagnose this outfit."
                + (f"\n\nWhat feels wrong to them: {complaint}" if complaint else "")
                + "\n\nTheir profile and wardrobe:\n"
                + json.dumps(context)
            ),
        },
        {"type": "input_image", "image_url": image_url},
    ]
    return call("critic", CRITIC, parts, Critique, max_output_tokens=2500)
