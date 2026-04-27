"""Gemini 2.5 Flash helper. All app-level LLM calls funnel through here.

Always forces thinkingBudget=0 (thinking tokens would blow the output budget
and cost 8-10x more for zero visible benefit on this workload).
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
DEFAULT_TIMEOUT = 60.0


class GeminiError(RuntimeError):
    pass


def gemini_generate(
    prompt: str,
    *,
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    json_mode: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Call Gemini 2.5 Flash. Returns plain text content."""
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY not set")

    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            ENDPOINT,
            params={"key": settings.gemini_api_key},
            json=body,
        )
    if resp.status_code != 200:
        raise GeminiError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise GeminiError(f"Gemini no candidates: {str(data)[:300]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts:
        finish = candidates[0].get("finishReason", "unknown")
        raise GeminiError(f"Gemini empty parts (finishReason={finish})")
    return parts[0].get("text", "") or ""
