"""One place to call the model, so every call gets counted.

Two cost levers live here: images are downscaled before they are ever sent,
and every reply is a strict JSON schema so we never pay for prose we discard.
"""

from __future__ import annotations

import base64
import io
import json
import time
from typing import Any, TypeVar

from openai import OpenAI
from PIL import Image
from pydantic import BaseModel

from config import (
    MAX_IMAGE_EDGE,
    PORTKEY_BASE_URL,
    cost_usd,
    provider,
)
from schemas import CallUsage

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None
_model: str = ""


def client() -> tuple[OpenAI, str]:
    """Build the client once and reuse it."""
    global _client, _model
    if _client is None:
        kind, key, model = provider()
        if kind == "portkey":
            _client = OpenAI(
                base_url=PORTKEY_BASE_URL,
                api_key=key,
                default_headers={"x-portkey-api-key": key},
            )
        else:
            _client = OpenAI(api_key=key)
        _model = model
    return _client, _model


# --- Images -----------------------------------------------------------------


def prepare_image(raw: bytes, max_edge: int = MAX_IMAGE_EDGE) -> str:
    """Downscale, strip metadata, return a JPEG data URL.

    Vision cost scales with pixels, so this is the single biggest saving in the
    app. It also drops EXIF, which is where phone photos carry GPS.
    """
    img = Image.open(io.BytesIO(raw))
    img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


# --- Strict schemas ---------------------------------------------------------


def _strictify(node: Any) -> Any:
    """Make a pydantic JSON schema satisfy OpenAI's strict mode."""
    if isinstance(node, dict):
        node.pop("default", None)
        if node.get("type") == "object":
            node["additionalProperties"] = False
            props = node.get("properties", {})
            if props:
                node["required"] = list(props.keys())
        return {k: _strictify(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def schema_of(model: type[BaseModel]) -> dict:
    return _strictify(model.model_json_schema())


# --- The call ---------------------------------------------------------------


def call(
    agent: str,
    system: str,
    parts: list[dict],
    out_model: type[T],
    max_output_tokens: int = 2000,
) -> tuple[T, CallUsage]:
    """Run one agent turn and return its parsed answer plus what it cost.

    `parts` is already-built Responses API content: input_text / input_image.
    """
    oai, model = client()
    started = time.monotonic()

    request: dict[str, Any] = {
        "model": model,
        "instructions": system,
        "input": [{"role": "user", "content": parts}],
        "max_output_tokens": max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": out_model.__name__,
                "schema": schema_of(out_model),
                "strict": True,
            }
        },
    }

    try:
        response = oai.responses.create(**request)
    except Exception:
        # Some gateways reject strict schemas. Fall back to asking plainly.
        request.pop("text", None)
        request["instructions"] = (
            system
            + "\n\nReply with JSON only, matching this schema exactly:\n"
            + json.dumps(out_model.model_json_schema())
        )
        response = oai.responses.create(**request)

    text = (response.output_text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    parsed = out_model.model_validate_json(text)

    usage = response.usage
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    odetails = getattr(usage, "output_tokens_details", None)
    reasoning = getattr(odetails, "reasoning_tokens", 0) or 0

    return parsed, CallUsage(
        agent=agent,
        model=model,
        input_tokens=in_tok,
        cached_tokens=cached,
        output_tokens=out_tok,
        reasoning_tokens=reasoning,
        cost_usd=cost_usd(in_tok, cached, out_tok),
        seconds=round(time.monotonic() - started, 2),
    )
