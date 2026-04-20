"""Weekly awards: aggregate last week's leaderboards and push Monday noon.

Leaders computed (Mon-Sun of previous week):
- 打擊王: highest batting average (min 10 AB)
- 自責分率王: lowest ERA (min 5.0 IP)
- 盜壘王: most stolen bases
- 保送王: most walks received (batter)
- 被三振王: most strikeouts (batter)
- 三振王: most strikeouts thrown (pitcher)
- 失誤王: most fielding errors

AI (via OpenRouter) writes a short commentary per award.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from app.config import settings
from app.db.client import get_db

logger = logging.getLogger(__name__)

MIN_AB_FOR_AVG = 10
MIN_IP_OUTS_FOR_ERA = 15  # 5.0 IP = 15 outs


def _last_week_range(today: date | None = None) -> tuple[str, str]:
    """Return (mon, sun) ISO dates for the week preceding `today`."""
    today = today or date.today()
    # weekday(): Mon=0 ... Sun=6
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)
    return last_monday.isoformat(), last_sunday.isoformat()


def _aggregate(start: str, end: str) -> dict:
    """Scan games with boxscore in [start, end] and aggregate per-player totals."""
    db = get_db()
    games = list(db["games"].find({
        "date": {"$gte": start, "$lte": end},
        "status": "final",
        "boxscore": {"$exists": True},
    }))

    batters: dict[tuple, dict] = {}  # (name, team_name) -> agg
    pitchers: dict[tuple, dict] = {}

    for g in games:
        bs = g.get("boxscore") or {}
        for b in bs.get("batting_summary", []):
            key = (b.get("name", ""), b.get("team_name", ""))
            if not key[0]:
                continue
            agg = batters.setdefault(key, {
                "name": key[0], "team_name": key[1],
                "hits": 0, "hr": 0, "rbi": 0, "at_bats": 0, "errors": 0,
                "walks": 0, "strikeouts": 0, "stolen_bases": 0, "games": 0,
            })
            agg["hits"] += b.get("hits", 0)
            agg["hr"] += b.get("hr", 0)
            agg["rbi"] += b.get("rbi", 0)
            agg["at_bats"] += b.get("at_bats", 0)
            agg["errors"] += b.get("errors", 0)
            agg["walks"] += b.get("walks", 0)
            agg["strikeouts"] += b.get("strikeouts", 0)
            agg["stolen_bases"] += b.get("stolen_bases", 0)
            agg["games"] += 1

        for p in bs.get("pitchers", []):
            key = (p.get("name", ""), p.get("team_name", ""))
            if not key[0]:
                continue
            agg = pitchers.setdefault(key, {
                "name": key[0], "team_name": key[1],
                "ip_outs": 0, "earned_runs": 0, "strikeouts": 0, "walks": 0, "hits_allowed": 0, "games": 0,
            })
            agg["ip_outs"] += p.get("ip_outs", 0)
            agg["earned_runs"] += p.get("earned_runs", 0)
            agg["strikeouts"] += p.get("strikeouts", 0)
            agg["walks"] += p.get("walks", 0) or 0
            agg["hits_allowed"] += p.get("hits_allowed", 0)
            agg["games"] += 1

    return {
        "batters": list(batters.values()),
        "pitchers": list(pitchers.values()),
        "game_count": len(games),
    }


def _pick_winners(agg: dict) -> dict:
    batters = agg["batters"]
    pitchers = agg["pitchers"]

    # 打擊王 — min AB threshold
    eligible_avg = [b for b in batters if b["at_bats"] >= MIN_AB_FOR_AVG]
    avg_king = None
    if eligible_avg:
        avg_king = max(eligible_avg, key=lambda b: b["hits"] / b["at_bats"])
        avg_king = dict(avg_king)
        avg_king["avg"] = avg_king["hits"] / avg_king["at_bats"]

    # 自責分率王 — min IP threshold
    eligible_era = [p for p in pitchers if p["ip_outs"] >= MIN_IP_OUTS_FOR_ERA]
    era_king = None
    if eligible_era:
        era_king = min(eligible_era, key=lambda p: (p["earned_runs"] * 27) / p["ip_outs"])
        era_king = dict(era_king)
        era_king["ip"] = f"{era_king['ip_outs'] // 3}.{era_king['ip_outs'] % 3}"
        era_king["era"] = (era_king["earned_runs"] * 27) / era_king["ip_outs"]

    # 盜壘王 — most stolen bases
    steal_king = max(
        (b for b in batters if b["stolen_bases"] > 0),
        key=lambda b: b["stolen_bases"],
        default=None,
    )

    # 保送王 — most walks received by a batter
    walk_king = max(
        (b for b in batters if b["walks"] > 0),
        key=lambda b: b["walks"],
        default=None,
    )

    # 被三振王 — batter with most strikeouts
    strikeout_victim_king = max(
        (b for b in batters if b["strikeouts"] > 0),
        key=lambda b: b["strikeouts"],
        default=None,
    )

    # 三振王 — pitcher with most Ks
    pitcher_k_king = max(
        (p for p in pitchers if p["strikeouts"] > 0),
        key=lambda p: p["strikeouts"],
        default=None,
    )

    # 失誤王 — most fielding errors
    error_king = max(
        (b for b in batters if b["errors"] > 0),
        key=lambda b: b["errors"],
        default=None,
    )

    return {
        "avg_king": avg_king,
        "era_king": era_king,
        "steal_king": steal_king,
        "walk_king": walk_king,
        "strikeout_victim_king": strikeout_victim_king,
        "pitcher_k_king": pitcher_k_king,
        "error_king": error_king,
    }


def _generate_ai_comments(winners: dict, date_range: tuple[str, str]) -> dict[str, str]:
    """Ask the LLM to write one short line per award. Returns {key: text}."""
    from openai import OpenAI

    lines = []
    if winners.get("avg_king"):
        w = winners["avg_king"]
        lines.append(f"- avg_king: {w['name']} ({w['team_name']}) — 打擊率 .{int(round(w['avg']*1000)):03d} ({w['hits']}/{w['at_bats']})，{w['hr']} HR {w['rbi']} RBI")
    if winners.get("era_king"):
        w = winners["era_king"]
        lines.append(f"- era_king: {w['name']} ({w['team_name']}) — ERA {w['era']:.2f} ({w['ip']}局 {w['earned_runs']}ER {w['strikeouts']}K)")
    if winners.get("steal_king"):
        w = winners["steal_king"]
        lines.append(f"- steal_king: {w['name']} ({w['team_name']}) — {w['stolen_bases']} 次盜壘成功")
    if winners.get("walk_king"):
        w = winners["walk_king"]
        lines.append(f"- walk_king: {w['name']} ({w['team_name']}) — 選到 {w['walks']} 次保送")
    if winners.get("strikeout_victim_king"):
        w = winners["strikeout_victim_king"]
        lines.append(f"- strikeout_victim_king: {w['name']} ({w['team_name']}) — 被三振 {w['strikeouts']} 次")
    if winners.get("pitcher_k_king"):
        w = winners["pitcher_k_king"]
        lines.append(f"- pitcher_k_king: {w['name']} ({w['team_name']}) — 三振對手 {w['strikeouts']} 次")
    if winners.get("error_king"):
        w = winners["error_king"]
        lines.append(f"- error_king: {w['name']} ({w['team_name']}) — {w['errors']} 失誤")

    if not lines:
        return {}

    start, end = date_range
    prompt = f"""你是中華職棒球評「TAKAMEI」，請針對上週 ({start} ~ {end}) 的七個球員獎項各寫一句短評。

要求：
- 每則評論 25~40 字繁體中文，語氣專業、有畫面感
- 點出關鍵數據或球員特色
- strikeout_victim_king (被三振最多) 和 error_king (失誤最多) 是「苦主」，請用鼓勵／帶點幽默的語氣，不要嘲諷
- 回傳嚴格的 JSON，形如：{{"avg_king": "...", "era_king": "...", "steal_king": "...", "walk_king": "...", "strikeout_victim_king": "...", "pitcher_k_king": "...", "error_king": "..."}}
- 只回 JSON，不要有其它文字或 code block

得獎資料：
{chr(10).join(lines)}"""

    try:
        client = OpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1")
        response = client.chat.completions.create(
            model="arcee-ai/trinity-large-preview:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=900,
        )
        text = (response.choices[0].message.content or "").strip()
        # Strip code fences if any
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except Exception as e:
        logger.warning(f"Weekly awards AI failed: {e}")
        return {}


def _build_awards_card(winners: dict, comments: dict, date_range: tuple[str, str]) -> dict | None:
    start, end = date_range
    sections = []

    def add_block(emoji: str, title: str, title_color: str, headline: str, stats: str, comment: str):
        block = [
            {"type": "box", "layout": "horizontal", "contents": [
                {"type": "text", "text": f"{emoji} {title}", "size": "sm", "color": title_color, "weight": "bold", "flex": 3},
                {"type": "text", "text": stats, "size": "sm", "color": "#FFFFFF", "align": "end", "flex": 4, "weight": "bold"},
            ]},
            {"type": "text", "text": headline, "size": "xs", "color": "#CCCCCC", "margin": "xs"},
        ]
        if comment:
            block.append({"type": "text", "text": comment, "size": "xxs", "color": "#888888", "wrap": True, "margin": "sm"})
        block.append({"type": "separator", "margin": "lg", "color": "#333333"})
        sections.extend(block)

    # Order follows user's requested list
    w = winners.get("avg_king")
    if w:
        add_block("📈", "打擊王", "#27AE60",
                  f"{w['name']} · {w['team_name']}",
                  f".{int(round(w['avg']*1000)):03d} ({w['hits']}/{w['at_bats']})",
                  comments.get("avg_king", ""))

    w = winners.get("era_king")
    if w:
        add_block("🥎", "自責分率王", "#3498DB",
                  f"{w['name']} · {w['team_name']}",
                  f"ERA {w['era']:.2f}",
                  comments.get("era_king", ""))

    w = winners.get("steal_king")
    if w:
        add_block("💨", "盜壘王", "#1ABC9C",
                  f"{w['name']} · {w['team_name']}",
                  f"{w['stolen_bases']} 次盜壘",
                  comments.get("steal_king", ""))

    w = winners.get("walk_king")
    if w:
        add_block("🎫", "保送王", "#E67E22",
                  f"{w['name']} · {w['team_name']}",
                  f"{w['walks']} 保送",
                  comments.get("walk_king", ""))

    w = winners.get("strikeout_victim_king")
    if w:
        add_block("💀", "被三振王", "#95A5A6",
                  f"{w['name']} · {w['team_name']}",
                  f"{w['strikeouts']} K",
                  comments.get("strikeout_victim_king", ""))

    w = winners.get("pitcher_k_king")
    if w:
        add_block("⚾", "三振王", "#F39C12",
                  f"{w['name']} · {w['team_name']}",
                  f"{w['strikeouts']} K",
                  comments.get("pitcher_k_king", ""))

    w = winners.get("error_king")
    if w:
        add_block("🧤", "失誤王", "#9B59B6",
                  f"{w['name']} · {w['team_name']}",
                  f"{w['errors']} 失誤",
                  comments.get("error_king", ""))

    if not sections:
        return None

    # Remove the trailing separator
    if sections and sections[-1].get("type") == "separator":
        sections.pop()

    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "14px",
            "contents": [
                {"type": "text", "text": "🏆 本週榮譽榜", "color": "#F39C12", "size": "lg", "weight": "bold"},
                {"type": "text", "text": f"{start} ~ {end}", "color": "#AAAAAA", "size": "xs", "margin": "xs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "15px",
            "contents": sections,
        },
    }


def push_weekly_awards(today: date | None = None, force: bool = False) -> dict:
    """Main entry: compute last week's awards and push to all whitelisted users."""
    from linebot.v3.messaging import (
        ApiClient, Configuration, MessagingApi,
        PushMessageRequest, FlexMessage, FlexContainer, TextMessage,
    )
    from app.db import whitelist_repo

    start, end = _last_week_range(today)
    db = get_db()
    push_key = f"weekly_awards_pushed_{end}"
    if not force and db["cache"].find_one({"_id": push_key}):
        logger.info(f"[Weekly Awards] Already pushed for week ending {end}, skipping")
        return {"status": "skipped", "reason": "already_pushed", "week": [start, end]}

    logger.info(f"[Weekly Awards] Aggregating {start} ~ {end}")

    agg = _aggregate(start, end)
    logger.info(f"[Weekly Awards] {agg['game_count']} games, {len(agg['batters'])} batters, {len(agg['pitchers'])} pitchers")

    if agg["game_count"] == 0:
        logger.info("[Weekly Awards] No games last week, skipping")
        return {"status": "skipped", "reason": "no_games", "week": [start, end]}

    winners = _pick_winners(agg)
    if not any(winners.values()):
        logger.info("[Weekly Awards] No qualifying winners, skipping")
        return {"status": "skipped", "reason": "no_winners", "week": [start, end]}

    comments = _generate_ai_comments(winners, (start, end))
    card = _build_awards_card(winners, comments, (start, end))
    if not card:
        return {"status": "skipped", "reason": "empty_card", "week": [start, end]}

    # Push to whitelisted users (fall back to all users if whitelist empty)
    recipients = [e["id"] for e in whitelist_repo.list_all()]
    if not recipients:
        recipients = [u["_id"] for u in db["users"].find({}, {"_id": 1})]

    configuration = Configuration(access_token=settings.line_channel_access_token)
    sent = 0
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        for uid in recipients:
            try:
                api.push_message(PushMessageRequest(
                    to=uid,
                    messages=[FlexMessage(
                        alt_text="🏆 本週榮譽榜",
                        contents=FlexContainer.from_dict(card),
                    )],
                ))
                sent += 1
            except Exception as e:
                logger.warning(f"Weekly awards push failed for {uid[:10]}...: {e}")

    # Mark as pushed (idempotency key per week)
    db["cache"].update_one(
        {"_id": push_key},
        {"$set": {"pushed": True, "pushed_at": datetime.now(), "sent": sent}},
        upsert=True,
    )

    logger.info(f"[Weekly Awards] Pushed to {sent}/{len(recipients)} users")
    return {
        "status": "ok",
        "week": [start, end],
        "games": agg["game_count"],
        "sent": sent,
        "recipients": len(recipients),
        "winners": {k: (v["name"] if v else None) for k, v in winners.items()},
    }
