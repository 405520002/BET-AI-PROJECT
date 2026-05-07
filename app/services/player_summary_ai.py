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
        axes: List of dicts with 'name' and 'value' (PR 0-100) keys. The scraper
              has already applied a role-aware view: pitcher axes carry "被"
              prefixes for opposing-batter stats and the PR is inverted so PR
              high = good for both batters and pitchers.
        user_query: Free-form user question in any language.

    Returns:
        A ~200-350 character Traditional Chinese summary, or an error string prefixed
        with "[AI 摘要產生失敗" if Gemini is unavailable.
    """
    effective_query = user_query.strip() or "請總結這位球員的整體表現"
    axes_lines = "\n".join(f"- {a['name']}: PR {a['value']}" for a in axes)

    if player.get("role") == "pitcher":
        role_note = (
            "這是投手。CPBL 進階數據頁面只公布「對方打者面對他」的指標，所以下面"
            "標示「被X」的數據（例如被打擊率、被上壘率、被長打率）都是對手打席表現；"
            "原始值越小越好，但下方提供的 PR 已經為投手反向過，PR 越高 = 該投手在這項上"
            "壓制力越強。三振%/揮空%/追打% 維持原始方向（投手讓對手三振、揮空、追打越多越好）。"
        )
    else:
        role_note = "這是野手。下方 PR 為 CPBL 公布的百分位，越高越好。"

    prompt = f"""你是 CPBL 中華職棒數據分析助手。以下是球員 {player['name_zh']} ({player['position_zh']}, {player['team']}, role={player['role']}) 的進階數據百分位 (PR, 0-100):

{role_note}

{axes_lines}

使用者問題: {effective_query}

請用繁體中文 200-350 字回答。先針對使用者的問題給出明確回應 (引用相關 PR 數值)，接著點出 1-2 項最強指標和 1-2 項待加強指標。語氣專業但易讀。不要捏造未提供的數據。對投手請務必用「被X」用語描述對手面對他的表現，不要把這些指標講成投手自己的打擊。"""
    try:
        resp = gemini_generate(prompt, temperature=0.7, max_output_tokens=1024, json_mode=False)
        return resp.strip()
    except Exception as e:
        logger.warning("gemini_generate failed: %s", e)
        return "[AI 摘要產生失敗，請稍後再試]"
