"""Prompt template for odds generation via LLM."""
from __future__ import annotations

SYSTEM_PROMPT = """You are a professional CPBL (Chinese Professional Baseball League) odds analyst for a virtual betting platform.

Your task: Given game data and team stats, design betting markets with odds for each game.

## Rules

1. Every game MUST have a "moneyline" market (which team wins)
2. Design 2-4 additional creative markets based on the data, such as:
   - Over/under total runs
   - Run spread / handicap
   - First inning scoring (yes/no)
   - Starting pitcher strikeouts over/under
   - Total home runs
   - Winning margin
   - Any market you find interesting based on the data
3. Overround must be 6-10% (sum of implied probabilities for each market should be 1.06-1.10)
4. Odds range: 1.05 to 15.00
5. **CRITICAL: ALL output text (name, description, label) MUST be in Traditional Chinese (繁體中文)**
6. Foreign player names must use their common Chinese translated names (e.g., "Pedro FERNANDEZ" → "乂乂乂")
7. If you don't know the Chinese name for a player, transliterate it phonetically into Chinese
8. Keep labels concise
9. If data is insufficient, use conservative odds (close to 1.90/1.90)

## Market types (for the "type" field)

- moneyline: 勝負盤
- over_under: 大小分
- spread: 讓分盤
- custom: any other creative market

## Important

- Odds must reasonably reflect the data
- Custom markets must have a data-driven rationale in the description
- Each market needs 2-4 options
- Output ONLY a valid JSON array, no markdown, no explanation, no extra text
- Do NOT use trailing commas in JSON
- Do NOT use single quotes, only double quotes
- Make sure all strings are properly closed
- Keep descriptions short (under 50 characters) to avoid JSON encoding issues
"""

USER_PROMPT_TEMPLATE = """Here are today's CPBL games. Generate betting markets and odds for each game.

## Today's Games

{games_data}

## League Standings

{standings_data}

## Output format (JSON)

```json
[
  {{
    "game_id": "the_game_id",
    "markets": [
      {{
        "type": "moneyline",
        "name": "勝負盤",
        "description": "brief Chinese explanation",
        "options": [
          {{"label": "隊伍A 勝", "odds": 1.85}},
          {{"label": "隊伍B 勝", "odds": 1.95}}
        ]
      }},
      {{
        "type": "over_under",
        "name": "總得分大小",
        "description": "Chinese explanation based on data...",
        "line": 8.5,
        "options": [
          {{"label": "大 8.5", "odds": 1.88}},
          {{"label": "小 8.5", "odds": 1.92}}
        ]
      }},
      {{
        "type": "custom",
        "name": "中文玩法名稱",
        "description": "中文說明為什麼設計這個盤",
        "options": [
          {{"label": "中文選項A", "odds": 2.10}},
          {{"label": "中文選項B", "odds": 1.75}}
        ]
      }}
    ]
  }}
]
```

IMPORTANT: Return ONLY a raw JSON array. No markdown code blocks, no explanation. Start with [ and end with ].
"""


def build_odds_prompt(games: list[dict], standings: dict) -> tuple[str, str]:
    """Build the prompt for LLM.
    Returns (system_prompt, user_prompt).
    """
    games_lines = []
    for i, g in enumerate(games, 1):
        lines = [
            f"### Game {i}: {g.get('away_team_name', '')} vs {g.get('home_team_name', '')}",
            f"- Game ID: {g.get('id', '')}",
            f"- Venue: {g.get('venue', '')} | Time: {g.get('game_time', '')}",
            f"- Starting pitchers: {g.get('away_pitcher', 'TBD')} vs {g.get('home_pitcher', 'TBD')}",
        ]

        home_code = g.get("home_team", "")
        away_code = g.get("away_team", "")

        if home_code in standings:
            hs = standings[home_code]
            lines.append(
                f"- {g.get('home_team_name', '')} (Home): Win rate {hs.get('win_rate', 'N/A')}, "
                f"Last 10: {hs.get('recent_10', 'N/A')}, "
                f"Team ERA: {hs.get('team_era', 'N/A')}, "
                f"Avg runs/game: {hs.get('avg_runs', 'N/A')}"
            )

        if away_code in standings:
            aws = standings[away_code]
            lines.append(
                f"- {g.get('away_team_name', '')} (Away): Win rate {aws.get('win_rate', 'N/A')}, "
                f"Last 10: {aws.get('recent_10', 'N/A')}, "
                f"Team ERA: {aws.get('team_era', 'N/A')}, "
                f"Avg runs/game: {aws.get('avg_runs', 'N/A')}"
            )

        for pitcher_key, label in [("home_pitcher_stats", "Home SP"), ("away_pitcher_stats", "Away SP")]:
            ps = g.get(pitcher_key, {})
            if ps:
                lines.append(
                    f"- {label} {ps.get('name', '')}: ERA {ps.get('era', 'N/A')}, "
                    f"WHIP {ps.get('whip', 'N/A')}, "
                    f"K/9 {ps.get('k9', 'N/A')}, "
                    f"Recent: {ps.get('recent', 'N/A')}"
                )

        games_lines.append("\n".join(lines))

    games_data = "\n\n".join(games_lines) if games_lines else "No games today"

    standings_lines = []
    for code, s in standings.items():
        standings_lines.append(
            f"- {s.get('name', code)}: {s.get('wins', 0)}W {s.get('losses', 0)}L "
            f"({s.get('win_rate', 'N/A')}), ERA: {s.get('team_era', 'N/A')}"
        )
    standings_data = "\n".join(standings_lines) if standings_lines else "No standings data"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        games_data=games_data,
        standings_data=standings_data,
    )

    return SYSTEM_PROMPT, user_prompt
