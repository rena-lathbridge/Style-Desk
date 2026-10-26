"""Keys, model choice, and the spend guardrails.

The teaching staff clone every repo into one folder and keep their .env one
level above it, so we look in both places, nearest first.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"

# Our own folder wins, then the folder above (submissions/.env).
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

# Course key only allows gpt-6-luna. A personal OpenAI key may use anything.
COURSE_MODEL = "gpt-6-luna"
OWN_KEY_MODEL = os.getenv("STYLE_MODEL", "gpt-6-luna")


class ConfigError(RuntimeError):
    """Raised when no usable API key was found."""


def provider() -> tuple[str, str, str]:
    """Return (kind, api_key, model). Prefers a personal OpenAI key."""
    own = os.getenv("OPENAI_API_KEY", "").strip()
    if own:
        return "openai", own, OWN_KEY_MODEL
    course = os.getenv("PORTKEY_API_KEY", "").strip()
    if course:
        return "portkey", course, COURSE_MODEL
    raise ConfigError(
        "No API key found. Copy .env.example to .env and set PORTKEY_API_KEY "
        "(or OPENAI_API_KEY). The app also reads a .env one folder above this one."
    )


# --- Spend guardrails -------------------------------------------------------
# Image tokens dominate this app's cost, so the limits are mostly about images.

MAX_IMAGE_BYTES = 8 * 1024 * 1024      # reject anything larger before upload
MAX_IMAGE_EDGE = 768                   # downscale longest edge before sending
MAX_INSPO_IMAGES = 6                   # per style-profile build
MAX_WARDROBE_ITEMS = 40                # per session
SESSION_TOKEN_BUDGET = 400_000         # hard stop for one browser session
MAX_NOTE_CHARS = 600                   # free-text the user can attach

# Published per-million prices for the course model. Override in .env if the
# course posts different numbers; every cost figure in the UI flows from here.
PRICE_INPUT_PER_M = float(os.getenv("PRICE_INPUT_PER_M", "1.25"))
PRICE_CACHED_INPUT_PER_M = float(os.getenv("PRICE_CACHED_INPUT_PER_M", "0.125"))
PRICE_OUTPUT_PER_M = float(os.getenv("PRICE_OUTPUT_PER_M", "10.00"))


def cost_usd(input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """Dollar cost of one call. Cached input is billed at the cheaper rate."""
    fresh = max(input_tokens - cached_tokens, 0)
    return (
        fresh / 1_000_000 * PRICE_INPUT_PER_M
        + cached_tokens / 1_000_000 * PRICE_CACHED_INPUT_PER_M
        + output_tokens / 1_000_000 * PRICE_OUTPUT_PER_M
    )
