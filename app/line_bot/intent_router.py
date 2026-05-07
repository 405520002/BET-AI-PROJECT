"""LLM-based intent router for free-form LINE messages.

Single-purpose: detect player-stat queries and extract the player name.
Returns {"intent": "player", "name": ..., "rest": ...} or {"intent": "unknown"}.
"""
from __future__ import annotations

import json
import logging
import re

from app.llm import gemini_generate, GeminiError

logger = logging.getLogger(__name__)


_PROMPT_TEMPLATE = """你是 CPBL LINE bot 的意圖分類器。判斷使用者訊息是否在詢問某位中華職棒球員的個人表現/數據/狀態。

只回傳 JSON，**不要** markdown、不要解釋。格式：
{{"intent": "player", "name": "<繁體中文球員名>", "rest": "<球員名以外的問題內容，可空字串>"}}
或
{{"intent": "unknown"}}

判定規則：
- 訊息明確指向「某位特定球員」的表現、能力、數據、狀態、狀況、近況等 → player
- 訊息是隊伍戰績、比賽結果、賽程、下注、儲值、規則、聊天閒談 → unknown
- 找不到具體球員名（只說「那個誰」「球星」這種模糊指稱） → unknown
- name 必須是訊息中實際出現的繁體中文名字（不要翻譯英文名、不要補全）
- rest 是把名字拿掉後使用者真正想問的內容，例如「最近狀態如何」「打擊強嗎」；沒有額外問題就空字串

使用者訊息：「{text}」

JSON："""


def classify_player_intent(text: str) -> dict:
    """Run Gemini to classify whether `text` is a player query.

    Returns one of:
      {"intent": "player", "name": str, "rest": str}
      {"intent": "unknown"}
    Failures (LLM unavailable, malformed JSON) degrade to {"intent": "unknown"}
    so the caller falls back to the standard help message.
    """
    text = (text or "").strip()
    if not text:
        return {"intent": "unknown"}

    prompt = _PROMPT_TEMPLATE.format(text=text.replace('"', "'"))
    try:
        raw = gemini_generate(
            prompt,
            temperature=0.0,
            max_output_tokens=128,
            json_mode=True,
        ).strip()
    except GeminiError as e:
        logger.warning("intent_router: gemini failed: %s", e)
        return {"intent": "unknown"}

    parsed = _safe_json_loads(raw)
    if not isinstance(parsed, dict):
        logger.warning("intent_router: non-dict result: %r", raw[:200])
        return {"intent": "unknown"}

    if parsed.get("intent") == "player":
        name = str(parsed.get("name") or "").strip()
        if not name:
            return {"intent": "unknown"}
        return {
            "intent": "player",
            "name": name,
            "rest": str(parsed.get("rest") or "").strip(),
        }
    return {"intent": "unknown"}


def _safe_json_loads(s: str):
    """Parse JSON tolerating ```json fences or trailing prose Gemini sometimes emits."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
