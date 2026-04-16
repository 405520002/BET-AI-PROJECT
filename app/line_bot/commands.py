"""Text command parsing and postback data parsing."""
from __future__ import annotations

from dataclasses import dataclass, field


# Text commands users can type
COMMANDS = {
    "今日賽事": "games",
    "賽事": "games",
    "比賽": "games",
    "儲值": "deposit",
    "存款": "deposit",
    "入金": "deposit",
    "排行榜": "leaderboard",
    "排行": "leaderboard",
    "我的戰績": "stats",
    "戰績": "stats",
    "餘額": "stats",
    "我的注單": "my_bets",
    "注單": "my_bets",
    "球隊戰績": "standings",
    "戰績表": "standings",
    "聯盟戰績": "standings",
    "近期賽果": "recent_results",
    "賽果": "recent_results",
    "比賽結果": "recent_results",
    "說明": "help",
    "幫助": "help",
    "help": "help",
}


def parse_text_command(text: str) -> str | None:
    """Parse user text into a command key, or None if not recognized."""
    text = text.strip()
    return COMMANDS.get(text)


@dataclass
class PostbackData:
    action: str = ""
    params: list[str] = field(default_factory=list)


def parse_postback(data: str) -> PostbackData:
    """Parse postback data string like 'bet|game_id|market_idx|selection|odds'."""
    parts = data.split("|")
    if not parts:
        return PostbackData()
    return PostbackData(action=parts[0], params=parts[1:])
