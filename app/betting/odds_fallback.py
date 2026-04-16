"""Rule-based fallback odds generator when Claude API is unavailable."""
from app.config import settings


def generate_fallback_odds(game: dict, standings: dict) -> dict:
    """Generate basic odds using team win rates."""
    home_code = game.get("home_team", "")
    away_code = game.get("away_team", "")
    home_name = game.get("home_team_name", "主隊")
    away_name = game.get("away_team_name", "客隊")

    # Get win rates
    home_wr = _get_win_rate(standings, home_code)
    away_wr = _get_win_rate(standings, away_code)

    # Home advantage
    home_wr += 0.03
    away_wr -= 0.03

    # Normalize
    total = home_wr + away_wr
    home_prob = home_wr / total
    away_prob = away_wr / total

    # Apply overround
    overround = settings.overround
    home_odds = _clamp_odds(1.0 / (home_prob * overround / 1.0))
    away_odds = _clamp_odds(1.0 / (away_prob * overround / 1.0))

    # Estimate total runs
    home_avg_runs = standings.get(home_code, {}).get("avg_runs", 4.5)
    away_avg_runs = standings.get(away_code, {}).get("avg_runs", 4.5)

    if isinstance(home_avg_runs, str):
        try:
            home_avg_runs = float(home_avg_runs)
        except ValueError:
            home_avg_runs = 4.5
    if isinstance(away_avg_runs, str):
        try:
            away_avg_runs = float(away_avg_runs)
        except ValueError:
            away_avg_runs = 4.5

    expected_total = home_avg_runs + away_avg_runs
    line = round(expected_total * 2) / 2
    if line == int(line):
        line += 0.5

    markets = [
        {
            "type": "moneyline",
            "name": "勝負盤",
            "description": f"根據雙方勝率計算",
            "options": [
                {"label": f"{home_name} 勝", "odds": round(home_odds, 2)},
                {"label": f"{away_name} 勝", "odds": round(away_odds, 2)},
            ],
        },
        {
            "type": "over_under",
            "name": f"總得分大小 {line}",
            "description": f"雙方場均得分合計約 {expected_total:.1f}",
            "line": line,
            "options": [
                {"label": f"大 {line}", "odds": 1.88},
                {"label": f"小 {line}", "odds": 1.92},
            ],
        },
    ]

    # Add spread if there's a clear favorite
    if abs(home_prob - away_prob) > 0.15:
        spread_line = 1.5
        markets.append({
            "type": "spread",
            "name": f"讓分盤",
            "description": f"強隊讓 {spread_line} 分",
            "line": spread_line,
            "options": [
                {"label": f"{home_name} -{spread_line}" if home_prob > away_prob else f"{away_name} -{spread_line}",
                 "odds": 2.10},
                {"label": f"{away_name} +{spread_line}" if home_prob > away_prob else f"{home_name} +{spread_line}",
                 "odds": 1.75},
            ],
        })

    return {"markets": markets}


def _get_win_rate(standings: dict, team_code: str) -> float:
    """Get team win rate from standings, default 0.500."""
    team = standings.get(team_code, {})
    wr = team.get("win_rate", 0.500)
    if isinstance(wr, str):
        try:
            wr = float(wr)
        except ValueError:
            wr = 0.500
    return max(0.1, min(0.9, wr))


def _clamp_odds(odds: float) -> float:
    return max(settings.min_odds, min(settings.max_odds, odds))
