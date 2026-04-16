"""Prompt template for Claude API odds generation."""
from __future__ import annotations

SYSTEM_PROMPT = """你是中華職棒 (CPBL) 虛擬下注平台的賠率分析師。
你的任務是根據提供的比賽數據，為每場比賽設計下注玩法和賠率。

## 規則

1. 每場比賽必須有「勝負盤」(moneyline) — 哪隊贏
2. 額外根據數據設計 2~4 個有趣的玩法，例如:
   - 大小分 (總得分 over/under)
   - 讓分盤 (handicap/spread)
   - 首局是否得分
   - 特定投手表現 (三振數、被安打數等)
   - 全壘打數
   - 贏分差距
   - 任何你覺得根據數據有故事性的玩法
3. 所有玩法的 overround 必須維持 6-10% (每個 market 的所有 option 的隱含機率總和應在 1.06~1.10)
4. 賠率範圍: 1.05 ~ 15.00
5. 用繁體中文描述玩法名稱和選項
6. 每個選項的 label 要簡潔明瞭
7. 如果數據不足，用保守賠率 (接近 1.90/1.90)

## 玩法類型 (type 欄位)

- moneyline: 勝負盤
- over_under: 大小分
- spread: 讓分盤
- custom: 其他自訂玩法

## 重要

- 賠率要合理反映數據，不要隨便給
- 特殊玩法要有根據，在 description 說明為什麼設計這個盤
- 每個 market 至少 2 個 options，最多 4 個
"""

USER_PROMPT_TEMPLATE = """以下是今日 CPBL 賽事數據，請為每場比賽生成下注玩法和賠率。

## 今日賽事

{games_data}

## 戰績資料

{standings_data}

## 請用以下 JSON 格式回傳

```json
[
  {{
    "game_id": "遊戲ID",
    "markets": [
      {{
        "type": "moneyline",
        "name": "勝負盤",
        "description": "簡短說明",
        "options": [
          {{"label": "隊伍A 勝", "odds": 1.85}},
          {{"label": "隊伍B 勝", "odds": 1.95}}
        ]
      }},
      {{
        "type": "over_under",
        "name": "總得分大小",
        "description": "根據XXX數據...",
        "line": 8.5,
        "options": [
          {{"label": "大 8.5", "odds": 1.88}},
          {{"label": "小 8.5", "odds": 1.92}}
        ]
      }},
      {{
        "type": "custom",
        "name": "自訂玩法名稱",
        "description": "為什麼設計這個玩法",
        "options": [
          {{"label": "選項A", "odds": 2.10}},
          {{"label": "選項B", "odds": 1.75}}
        ]
      }}
    ]
  }}
]
```

只回傳 JSON，不要加其他文字。
"""


def build_odds_prompt(games: list[dict], standings: dict) -> tuple[str, str]:
    """Build the prompt for Claude API.
    Returns (system_prompt, user_prompt).
    """
    # Format games data
    games_lines = []
    for i, g in enumerate(games, 1):
        lines = [
            f"### 第{i}場: {g.get('away_team_name', '')} vs {g.get('home_team_name', '')}",
            f"- Game ID: {g.get('id', '')}",
            f"- 球場: {g.get('venue', '')} | 時間: {g.get('game_time', '')}",
            f"- 先發投手: {g.get('away_pitcher', 'TBD')} vs {g.get('home_pitcher', 'TBD')}",
        ]

        # Add team stats if available
        home_code = g.get("home_team", "")
        away_code = g.get("away_team", "")

        if home_code in standings:
            hs = standings[home_code]
            lines.append(f"- {g.get('home_team_name', '')} (主): 勝率 {hs.get('win_rate', 'N/A')}, "
                        f"近10場 {hs.get('recent_10', 'N/A')}, "
                        f"團隊ERA {hs.get('team_era', 'N/A')}, "
                        f"場均得分 {hs.get('avg_runs', 'N/A')}")

        if away_code in standings:
            aws = standings[away_code]
            lines.append(f"- {g.get('away_team_name', '')} (客): 勝率 {aws.get('win_rate', 'N/A')}, "
                        f"近10場 {aws.get('recent_10', 'N/A')}, "
                        f"團隊ERA {aws.get('team_era', 'N/A')}, "
                        f"場均得分 {aws.get('avg_runs', 'N/A')}")

        # Pitcher stats
        for pitcher_key, pitcher_label in [("home_pitcher_stats", "主投"), ("away_pitcher_stats", "客投")]:
            ps = g.get(pitcher_key, {})
            if ps:
                lines.append(f"- {pitcher_label} {ps.get('name', '')}: ERA {ps.get('era', 'N/A')}, "
                            f"WHIP {ps.get('whip', 'N/A')}, "
                            f"K/9 {ps.get('k9', 'N/A')}, "
                            f"近況: {ps.get('recent', 'N/A')}")

        games_lines.append("\n".join(lines))

    games_data = "\n\n".join(games_lines) if games_lines else "無賽事資料"

    # Format standings
    standings_lines = []
    for code, s in standings.items():
        standings_lines.append(
            f"- {s.get('name', code)}: {s.get('wins', 0)}勝 {s.get('losses', 0)}敗 "
            f"勝率 {s.get('win_rate', 'N/A')}"
        )
    standings_data = "\n".join(standings_lines) if standings_lines else "無戰績資料"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        games_data=games_data,
        standings_data=standings_data,
    )

    return SYSTEM_PROMPT, user_prompt
