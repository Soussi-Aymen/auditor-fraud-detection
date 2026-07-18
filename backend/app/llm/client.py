"""OpenAI client helpers. Structured Outputs only; offline when no API key."""

from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_SYSTEM_STYLE = (
    "You assist German financial-statement auditors. "
    "Write in clear professional English. "
    "Style only: audit headline + short evidence story. "
    "Never invent entities, amounts, dates, files, or row locators that are not in the user input. "
    "Never invent findings. Never set or change a confidence percentage. "
    "Do not reference any sealed ground-truth dossier or training examples."
)


def openai_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def model_primary() -> str:
    return os.environ.get("OPENAI_MODEL_PRIMARY", "gpt-5.6").strip() or "gpt-5.6"


def model_fast() -> str:
    return os.environ.get("OPENAI_MODEL_FAST", "gpt-5.6-terra").strip() or "gpt-5.6-terra"


def structured_parse(
    *,
    model: str,
    user_content: str,
    response_model: type[T],
    system: str = _SYSTEM_STYLE,
) -> T:
    """Call OpenAI with Structured Outputs; raises if the key is missing or the call fails."""
    if not openai_enabled():
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI()
    # Prefer Responses API parse; fall back to chat.completions.parse.
    try:
        resp = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            text_format=response_model,
        )
        parsed = resp.output_parsed
        if parsed is None:
            raise RuntimeError("empty structured output")
        return parsed
    except (AttributeError, TypeError, ValueError):
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            response_format=response_model,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("empty structured output") from None
        return parsed
