"""AI-generated player summary using Gemini.

Public API:
    generate_player_summary(player, axes, user_query) -> str
"""
from __future__ import annotations

import logging

from app.llm import gemini_generate

logger = logging.getLogger(__name__)


def generate_player_summary(player: dict, axes: list[dict], user_query: str) -> str:
    """Generate a Chinese summary of a player's PR axes given a free-form user query.

    Args:
        player: Player dict with keys name_zh, position_zh, team, role (from fetch_player_advanced_stats).
        axes: List of dicts with 'name' and 'value' (PR 0-100) keys.
        user_query: Free-form user question in any language.

    Returns:
        A ~200-350 character Traditional Chinese summary, or an error string prefixed
        with "[AI 摘要產生失敗" if Gemini is unavailable.
    """
    effective_query = user_query.strip() or "請總結這位球員的整體表現"
    axes_lines = "\n".join(f"- {a['name']}: PR {a['value']}" for a in axes)
    prompt = f"""你是 CPBL 中華職棒數據分析助手。以下是球員 {player['name_zh']} ({player['position_zh']}, {player['team']}, role={player['role']}) 的中職進階數據百分位 (PR, 0-100，越高越好):
{axes_lines}

使用者問題: {effective_query}

請用繁體中文 200-350 字回答。先針對使用者的問題給出明確回應 (引用相關 PR 數值)，接著點出 1-2 項最強指標和 1-2 項待加強指標。語氣專業但易讀。不要捏造未提供的數據。"""
    try:
        resp = gemini_generate(prompt, temperature=0.7, max_output_tokens=1024, json_mode=False)
        return resp.strip()
    except Exception as e:
        logger.warning("gemini_generate failed: %s", e)
        return "[AI 摘要產生失敗，請稍後再試]"
