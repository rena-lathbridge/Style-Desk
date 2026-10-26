"""HTTP surface for the styling coach.

Run from the repo root:  uvicorn app.main:app --port 8000
Then open:               http://127.0.0.1:8000
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agents
import fetching
import safety
from config import (
    MAX_IMAGE_BYTES,
    MAX_INSPO_IMAGES,
    MAX_WARDROBE_ITEMS,
    ConfigError,
    WEB_DIR,
)
from llm import prepare_image
from safety import BudgetExceeded
from schemas import Principle, StyleProfile
from store import CACHE, image_key, seed_wardrobe, session

app = FastAPI(title="Style Coach", version="1.0.0")


@app.exception_handler(BudgetExceeded)
async def _budget_handler(_request, exc: BudgetExceeded):
    return JSONResponse(status_code=429, content={"error": str(exc)})


@app.exception_handler(ConfigError)
async def _config_handler(_request, exc: ConfigError):
    return JSONResponse(status_code=503, content={"error": str(exc)})


# --- helpers ----------------------------------------------------------------


async def _read_image(upload: UploadFile) -> bytes:
    raw = await upload.read()
    if not raw:
        raise HTTPException(400, "That file was empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(
            413,
            f"{upload.filename} is larger than "
            f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB. Please shrink it first.",
        )
    return raw


def _check_injection(sess, text: str, where: str) -> None:
    """Image text is reported by the agent; this is where we judge it."""
    hit = safety.scan_embedded_text(text)
    if hit:
        sess.safety.add(
            kind="prompt_injection",
            detail=f'Text inside the {where} photo read: "{hit}"',
            action="Reported to you and ignored. It did not reach the stylist.",
        )


def _guard_note(sess, note: str) -> str:
    """Refuse body talk before it costs a model call."""
    note = safety.clamp_note(note)
    hit = safety.body_talk(note)
    if hit:
        sess.safety.add(
            kind="body_image",
            detail=f'Your note mentioned "{hit}".',
            action="Refused before any model call. Nothing was spent.",
        )
        raise HTTPException(422, safety.BODY_REFUSAL)
    return note


# --- routes -----------------------------------------------------------------


@app.get("/api/state/{sid}")
def state(sid: str):
    sess = session(sid)
    return {
        "profile": sess.profile.model_dump() if sess.profile else None,
        "wardrobe": [g.model_dump() for g in sess.wardrobe],
        "receipt": sess.receipt(),
        "cache": {"hits": CACHE.hits, "misses": CACHE.misses},
    }


def _collect_urls(sess, raw: str, budget_left: int) -> list[bytes]:
    """Fetch pasted image URLs, refusing anything that is not a public image."""
    wanted = [u.strip() for u in raw.replace(",", "\n").split("\n") if u.strip()]
    if not wanted:
        return []

    boards = [u for u in wanted if fetching.is_board_link(u)]
    if boards:
        raise HTTPException(
            422,
            "Pinterest board links will not work: the board page sends no pins to "
            "a server, and Pinterest's robots.txt disallows fetching it. Open the "
            "board, right-click a pin you like, choose 'Copy image address', and "
            "paste those links instead \u2014 or just drag the pins straight onto "
            "the box above.",
        )

    if len(wanted) > budget_left:
        raise HTTPException(
            400, f"Up to {MAX_INSPO_IMAGES} inspiration images at a time."
        )

    out: list[bytes] = []
    for url in wanted:
        try:
            out.append(fetching.fetch_image(url).data)
        except fetching.FetchRefused as exc:
            sess.safety.add(
                kind="url_refused",
                detail=f"{url[:80]} \u2014 {exc}",
                action="Not fetched. Nothing was sent to the model.",
            )
            raise HTTPException(422, str(exc)) from exc
    return out


@app.post("/api/profile/{sid}")
async def build_profile(
    sid: str,
    files: list[UploadFile] = File(default=[]),
    urls: str = Form(""),
    note: str = Form(""),
):
    """Teach me my style: inspiration photos in, named principles out.

    Images can be uploaded or pasted as links, in any mix.
    """
    sess = session(sid)
    note = _guard_note(sess, note)
    sess.budget.check()

    if len(files) > MAX_INSPO_IMAGES:
        raise HTTPException(
            400, f"Up to {MAX_INSPO_IMAGES} inspiration images at a time."
        )

    raw_images = [await _read_image(f) for f in files]
    raw_images += _collect_urls(sess, urls, MAX_INSPO_IMAGES - len(raw_images))
    if not raw_images:
        raise HTTPException(400, "Add at least one inspiration image or link.")

    prepared = [prepare_image(b) for b in raw_images]
    profile, usage = agents.analyze(prepared, note)
    sess.record(usage)
    _check_injection(sess, profile.embedded_text, "inspiration")

    sess.profile = profile
    return {"profile": profile.model_dump(), "receipt": sess.receipt()}


class ProfileEdit(BaseModel):
    """The profile is the user's to correct; that is the point of the app."""

    headline: str
    principles: list[Principle]
    palette: list[str]
    avoid: list[str]


@app.put("/api/profile/{sid}")
def edit_profile(sid: str, edit: ProfileEdit):
    sess = session(sid)
    sess.profile = StyleProfile(embedded_text="", **edit.model_dump())
    return {"profile": sess.profile.model_dump()}


@app.post("/api/wardrobe/seed/{sid}")
def load_seed(sid: str):
    sess = session(sid)
    sess.wardrobe = seed_wardrobe()
    return {"wardrobe": [g.model_dump() for g in sess.wardrobe]}


@app.post("/api/wardrobe/{sid}")
async def add_garments(sid: str, files: list[UploadFile] = File(...)):
    """Catalog items. A repeat photo is served from cache for free."""
    sess = session(sid)
    added = []
    for upload in files:
        if len(sess.wardrobe) >= MAX_WARDROBE_ITEMS:
            raise HTTPException(400, f"Wardrobe is capped at {MAX_WARDROBE_ITEMS} items.")
        raw = await _read_image(upload)
        key = image_key(raw)

        cached = CACHE.get(key)
        if cached is not None:
            sess.record_cache_hit("cataloger")
            garment = cached.model_copy(update={"id": f"U{len(sess.wardrobe) + 1}"})
        else:
            sess.budget.check()
            garment, usage = agents.catalog(
                prepare_image(raw), f"U{len(sess.wardrobe) + 1}"
            )
            sess.record(usage)
            CACHE.put(key, garment)

        # Runs on both paths. The cache stores what the agent saw, so an image
        # that carried an injection must still be flagged the second time it is
        # uploaded, even though no model call happened.
        _check_injection(sess, garment.embedded_text, "garment")

        sess.wardrobe.append(garment)
        added.append(garment.model_dump())

    return {
        "added": added,
        "wardrobe": [g.model_dump() for g in sess.wardrobe],
        "receipt": sess.receipt(),
        "cache": {"hits": CACHE.hits, "misses": CACHE.misses},
    }


class OutfitRequest(BaseModel):
    occasion: str = ""


@app.post("/api/outfits/{sid}")
def build_outfits(sid: str, req: OutfitRequest):
    """Help me recreate it: text-only, so this is the cheap call."""
    sess = session(sid)
    # Safety first: refuse body talk before we even look at session state, so
    # the guard fires the same way on a fresh session as on a warm one.
    occasion = _guard_note(sess, req.occasion)
    sess.budget.check()
    if sess.profile is None:
        raise HTTPException(400, "Build a style profile first.")
    if not sess.wardrobe:
        raise HTTPException(400, "Add some clothes first, or load the demo closet.")
    outfits, usage = agents.style(sess.profile, sess.wardrobe, occasion)
    sess.record(usage)
    return {"outfits": outfits.model_dump(), "receipt": sess.receipt()}


@app.post("/api/critique/{sid}")
async def debug_outfit(
    sid: str,
    file: UploadFile = File(...),
    complaint: str = Form(""),
):
    """Debug my outfit: what is and isn't working, tied to the principles."""
    sess = session(sid)
    complaint = _guard_note(sess, complaint)
    sess.budget.check()
    if sess.profile is None:
        raise HTTPException(400, "Build a style profile first.")
    url = prepare_image(await _read_image(file))
    result, usage = agents.critique(url, sess.profile, complaint, sess.wardrobe)
    sess.record(usage)
    _check_injection(sess, result.embedded_text, "outfit")

    return {"critique": result.model_dump(), "receipt": sess.receipt()}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
