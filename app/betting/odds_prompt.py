"""Two-step prompt: Step 1 designs markets, Step 2 formats to JSON."""
from __future__ import annotations


def build_design_prompt(games: list[dict], standings: dict) -> str:
    """Step 1: Ask AI to design betting markets in natural language."""

    games_text = ""
    for i, g in enumerate(games, 1):
        home_code = g.get("home_team", "")
        away_code = g.get("away_team", "")

        home_stats = ""
        if home_code in standings:
            s = standings[home_code]
            home_stats = f"Win rate {s.get('win_rate','N/A')}, Last 10: {s.get('recent_10','N/A')}, ERA: {s.get('team_era','N/A')}"

        away_stats = ""
        if away_code in standings:
            s = standings[away_code]
            away_stats = f"Win rate {s.get('win_rate','N/A')}, Last 10: {s.get('recent_10','N/A')}, ERA: {s.get('team_era','N/A')}"

        games_text += f"""
Game {i} (ID: {g.get('id','')})
  {g.get('away_team_name','')} (Away) vs {g.get('home_team_name','')} (Home)
  Venue: {g.get('venue','')} | Time: {g.get('game_time','')}
  Pitchers: {g.get('away_pitcher','TBD')} vs {g.get('home_pitcher','TBD')}
  Home stats: {home_stats}
  Away stats: {away_stats}
"""

    return f"""You are a CPBL baseball betting analyst. Design betting markets for these games.

{games_text}

For each game, design:
1. Moneyline (which team wins) with decimal odds
2. Over/under total runs with a line
3. 1-2 creative markets based on the data (e.g. spread, first inning scoring, pitcher strikeouts, winning margin)

Rules:
- Each market needs 2-4 options with decimal odds (e.g. 1.85, 2.10)
- House edge: the implied probabilities should sum to 1.06-1.10
- Odds range: 1.05 to 15.00
- Write ALL market names, option labels, and descriptions in Traditional Chinese (繁體中文)
- For foreign player names, use Chinese transliteration
- Give a brief reason for each market

Just write it out naturally, don't worry about JSON format."""


def build_json_prompt(design_text: str, game_ids: list[str]) -> str:
    """Step 2: Convert the natural language design into strict JSON."""

    return f"""Convert the following betting market design into a JSON array.

DESIGN:
{design_text}

GAME IDS: {game_ids}

OUTPUT FORMAT - Return ONLY a valid JSON array, starting with [ and ending with ]. No markdown, no explanation.

Each element:
{{"game_id": "the_game_id", "markets": [{{"type": "moneyline or over_under or spread or custom", "name": "中文名稱", "description": "中文說明", "options": [{{"label": "中文選項", "odds": 1.85}}]}}]}}

Rules:
- type must be one of: moneyline, over_under, spread, custom
- All name/description/label must be in Traditional Chinese
- odds must be numbers (not strings)
- No trailing commas
- No single quotes, only double quotes

Start your response with [ immediately."""


def build_json_prompt_single(design_text: str, game_id: str) -> str:
    """Step 2 (single game): Convert design to JSON for one game only."""

    return f"""Extract the betting markets for game ID "{game_id}" from the design below and convert to JSON.

DESIGN:
{design_text}

OUTPUT - Return ONLY a valid JSON array with one object for this game. No markdown, no explanation.

Format:
[{{"game_id": "{game_id}", "markets": [{{"type": "moneyline", "name": "中文名稱", "description": "中文說明(30字內)", "options": [{{"label": "中文選項", "odds": 1.85}}]}}]}}]

Rules:
- type: moneyline, over_under, spread, or custom
- All text in Traditional Chinese
- odds must be numbers
- description must be under 30 characters
- No trailing commas

Start with [ immediately."""
