"""Settlement engine: rule-based first, AI for custom bets."""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from openai import OpenAI

from app.config import settings
from app.db import game_repo, bet_repo, user_repo, tx_repo

logger = logging.getLogger(__name__)


def _get_ai_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )


# ============================================================
# Main settlement flow
# ============================================================

def settle_game(game_id: str, boxscore: dict | None = None) -> dict:
    """Settle all pending bets for a game.
    boxscore: detailed box score data from cpbl_boxscore scraper.
    """
    game = game_repo.get_game(game_id)
    if not game:
        return {"error": "Game not found"}

    if game.get("status") == "postponed":
        return refund_game(game_id)

    if game.get("status") != "final":
        return {"error": f"Game status is '{game.get('status')}', cannot settle"}

    pending_bets = bet_repo.get_bets_by_game(game_id, status="pending")
    if not pending_bets:
        return {"settled": 0, "refunded": 0, "total_payout": 0}

    # Split bets: rule-based vs needs-AI
    rule_bets = []
    ai_bets = []
    for bet in pending_bets:
        if _can_rule_settle(bet, game, boxscore):
            rule_bets.append(bet)
        else:
            ai_bets.append(bet)

    settled = 0
    total_payout = 0

    # Rule-based settlement
    for bet in rule_bets:
        outcome, payout, reason = _rule_evaluate(bet, game, boxscore)
        _apply_settlement(bet, game_id, outcome, payout, reason)
        settled += 1
        if outcome == "won":
            total_payout += payout

    # AI settlement for custom bets
    if ai_bets and boxscore:
        ai_results = _ai_evaluate_bets(ai_bets, game, boxscore)
        for bet, result_tuple in zip(ai_bets, ai_results):
            outcome, payout, reason = result_tuple
            _apply_settlement(bet, game_id, outcome, payout, reason)
            settled += 1
            if outcome == "won":
                total_payout += payout

    logger.info(f"Settled game {game_id}: {settled} bets (rule:{len(rule_bets)} ai:{len(ai_bets)}), payout:{total_payout}")
    return {"settled": settled, "refunded": 0, "total_payout": total_payout,
            "rule_based": len(rule_bets), "ai_settled": len(ai_bets)}


def refund_game(game_id: str) -> dict:
    """Refund all pending bets for a postponed game."""
    pending_bets = bet_repo.get_bets_by_game(game_id, status="pending")
    refunded = 0

    for bet in pending_bets:
        amount = bet.get("amount", 0)
        bet_repo.update_bet(bet["id"], {
            "status": "refunded",
            "payout": amount,
            "profit": 0,
            "settled_at": date.today().isoformat(),
            "settlement_note": "延賽/取消 - 全額退款",
        })

        user = user_repo.get_user(bet["user_id"])
        if user:
            new_balance = user.get("balance", 0) + amount
            user_repo.update_user(bet["user_id"], {"balance": new_balance})
            tx_repo.create_transaction({
                "user_id": bet["user_id"],
                "type": "refund",
                "amount": amount,
                "balance_after": new_balance,
                "bet_id": bet["id"],
                "game_id": game_id,
                "note": f"延賽退款 {amount:,} 元",
            })

        refunded += 1

    game_repo.update_game_status(game_id, "postponed")
    return {"settled": 0, "refunded": refunded, "total_payout": 0}


def settle_all_games_for_date(date_str: str, boxscores: dict | None = None) -> dict:
    """Settle all games for a date. boxscores: {game_id: boxscore_dict}"""
    games = game_repo.get_games_by_date(date_str)
    results = {"total_settled": 0, "total_refunded": 0, "total_payout": 0, "games_processed": 0}

    for game in games:
        bs = boxscores.get(game["id"]) if boxscores else None
        if game.get("status") == "final":
            r = settle_game(game["id"], bs)
        elif game.get("status") == "postponed":
            r = refund_game(game["id"])
        else:
            continue

        if "error" not in r:
            results["total_settled"] += r.get("settled", 0)
            results["total_refunded"] += r.get("refunded", 0)
            results["total_payout"] += r.get("total_payout", 0)
            results["games_processed"] += 1

    return results


# ============================================================
# Rule-based settlement
# ============================================================

RULE_TYPES = {"moneyline", "over_under", "spread", "first_inning", "total_hr",
              "win_margin", "pitcher_k", "pitcher_er", "team_hits", "team_runs"}


def _can_rule_settle(bet: dict, game: dict, boxscore: dict | None) -> bool:
    """Check if this bet can be settled with rules."""
    bet_type = bet.get("bet_type", "")

    # These always work with just scores
    if bet_type in ("moneyline", "over_under", "spread"):
        return True

    # These need boxscore
    if bet_type in ("first_inning", "total_hr", "win_margin", "pitcher_k",
                    "pitcher_er", "team_hits", "team_runs"):
        return boxscore is not None

    # Legacy custom type - try to match by market_name keywords
    if bet_type == "custom" and boxscore:
        market_name = bet.get("market_name", "")
        if "首局" in market_name:
            return True
        if "全壘打" in market_name:
            return True
        if "贏" in market_name and "分" in market_name:
            return True
        if "三振" in market_name or "K" in bet.get("selection", ""):
            return True
        if "失分" in market_name or "自責" in market_name:
            return True
        if "安打" in market_name:
            return True

    return False


def _rule_evaluate(bet: dict, game: dict, boxscore: dict | None) -> tuple[str, int, str]:
    """Evaluate a bet using rules. Returns (outcome, payout, reason)."""
    home_score = game.get("home_score", 0)
    away_score = game.get("away_score", 0)
    total_runs = home_score + away_score
    winner = game.get("winner", "")
    home_name = game.get("home_team_name", "")
    away_name = game.get("away_team_name", "")
    bet_type = bet.get("bet_type", "")
    selection = bet.get("selection", "")
    odds = bet.get("odds", 1.0)
    amount = bet.get("amount", 0)
    score_text = f"{away_name} {away_score}:{home_score} {home_name}"

    # Moneyline
    if bet_type == "moneyline":
        winner_name = home_name if winner == "home" else away_name
        if home_name in selection and winner == "home":
            return ("won", round(amount * odds), f"實際: {score_text}，{winner_name}勝")
        elif away_name in selection and winner == "away":
            return ("won", round(amount * odds), f"實際: {score_text}，{winner_name}勝")
        return ("lost", 0, f"實際: {score_text}，{winner_name}勝")

    # Over/Under
    if bet_type == "over_under":
        line = _extract_number(selection)
        if line is None:
            return ("lost", 0, "無法解析分數線")
        reason = f"實際總分{total_runs} vs 盤口{line}"
        if "大" in selection and total_runs > line:
            return ("won", round(amount * odds), reason)
        elif "小" in selection and total_runs < line:
            return ("won", round(amount * odds), reason)
        elif total_runs == line:
            return ("refunded", amount, f"{reason}，平盤退款")
        return ("lost", 0, reason)

    # Spread
    if bet_type == "spread":
        line = _extract_number(selection)
        if line is None:
            return ("lost", 0, "無法解析讓分線")
        margin = home_score - away_score
        if home_name in selection:
            adjusted = margin + (line if "-" in selection else -line)
        else:
            adjusted = -margin + (line if "+" in selection else -line)
        reason = f"實際: {score_text}，分差{abs(margin)}"
        if adjusted > 0:
            return ("won", round(amount * odds), reason)
        elif adjusted == 0:
            return ("refunded", amount, f"{reason}，平盤退款")
        return ("lost", 0, reason)

    # Custom with boxscore data
    if boxscore:
        market_name = bet.get("market_name", "")

        # First inning run
        if "首局" in market_name:
            fir = boxscore.get("first_inning_runs", 0)
            reason = f"實際首局得分: {fir}分"
            if ("有" in selection or "是" in selection) and fir > 0:
                return ("won", round(amount * odds), reason)
            elif ("無" in selection or "否" in selection) and fir == 0:
                return ("won", round(amount * odds), reason)
            return ("lost", 0, reason)

        # Total HR
        if "全壘打" in market_name:
            hr = boxscore.get("total_hr", 0)
            line = _extract_number(selection)
            reason = f"實際全壘打: {hr}支"
            if line is not None:
                if "大" in selection and hr > line:
                    return ("won", round(amount * odds), reason)
                elif "小" in selection and hr < line:
                    return ("won", round(amount * odds), reason)
                elif hr == line:
                    return ("refunded", amount, f"{reason}，平盤退款")
            elif "0" in selection and hr == 0:
                return ("won", round(amount * odds), reason)
            elif "1+" in selection and hr >= 1:
                return ("won", round(amount * odds), reason)
            return ("lost", 0, reason)

        # Winning margin
        if "贏" in market_name and "分" in market_name:
            margin = boxscore.get("winning_margin", 0)
            reason = f"實際勝分差: {margin}分"
            if "1-2" in selection and 1 <= margin <= 2:
                return ("won", round(amount * odds), reason)
            elif "3" in selection and ("以上" in selection or "及以上" in selection) and margin >= 3:
                return ("won", round(amount * odds), reason)
            return ("lost", 0, reason)

    return ("lost", 0, "")


# ============================================================
# AI settlement (for bets rule-based can't handle)
# ============================================================

def _ai_evaluate_bets(bets: list[dict], game: dict, boxscore: dict) -> list[tuple[str, int]]:
    """Use AI to evaluate custom bets that rules can't handle."""
    bets_desc = []
    for i, bet in enumerate(bets):
        bets_desc.append(
            f"注單{i+1}: 玩法「{bet.get('market_name', '')}」選擇「{bet.get('selection', '')}」"
            f" 賠率{bet.get('odds', 0)} 金額{bet.get('amount', 0)}元"
        )

    prompt = f"""你是一位專業的中華職棒 (CPBL) 棒球分析員兼虛擬下注結算裁判。

## 棒球術語提醒
- K = 三振 (strikeout)，不是數字的「千」。例如 "7K" 表示三振 7 次
- over 5.5 K = 三振數超過 5.5 次（即 6 次以上算贏）
- under 5.5 K = 三振數低於 5.5 次（即 5 次以下算贏）
- HR = 全壘打 (Home Run)
- ER = 自責分 (Earned Run)
- IP = 投球局數 (Innings Pitched)
- 先發投手 = 每隊第一位上場的投手

## 比賽結果
{boxscore.get('raw_text', '')}

## 待結算注單
{chr(10).join(bets_desc)}

## 判斷規則
1. 仔細比對注單的選擇和比賽結果
2. 例如「over 5.5 K」且先發投手實際三振 7 次 → 7 > 5.5 → won
3. 例如「失分小於或等於 3.5」且該隊實際失 1 分 → 1 <= 3.5 → won
4. 如果注單涉及「先發投手」，只看該隊第一位投手的數據

## 回傳格式（JSON array of objects）
每個注單回傳 outcome 和 reason，reason 要簡短說明實際數據和判斷依據，例如：
[
  {{"outcome": "won", "reason": "王維中實際7K > 5.5K"}},
  {{"outcome": "lost", "reason": "全壘打0支 < 1.5"}}
]

只回傳 JSON array，不要加其他文字。"""

    try:
        client = _get_ai_client()
        response = client.chat.completions.create(
            model="nvidia/nemotron-3-super-120b-a12b:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=256,
        )
        text = response.choices[0].message.content.strip()

        if "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            if text.startswith("json"):
                text = text[4:].strip()

        ai_results = json.loads(text)

        results = []
        for i, bet in enumerate(bets):
            if i < len(ai_results):
                item = ai_results[i]
                if isinstance(item, dict):
                    outcome = item.get("outcome", "lost")
                    reason = item.get("reason", "")
                else:
                    outcome = item
                    reason = ""
            else:
                outcome = "lost"
                reason = ""

            amount = bet.get("amount", 0)
            odds = bet.get("odds", 1.0)
            if outcome == "won":
                results.append(("won", round(amount * odds), reason))
            else:
                results.append(("lost", 0, reason))
        return results

    except Exception as e:
        logger.error(f"AI settlement failed: {e}, refunding all")
        return [("refunded", bet.get("amount", 0), "AI結算失敗，全額退款") for bet in bets]


# ============================================================
# Helpers
# ============================================================

def _apply_settlement(bet: dict, game_id: str, outcome: str, payout: int, reason: str = ""):
    """Apply settlement result to bet and user."""
    amount = bet.get("amount", 0)
    profit = payout - amount if outcome == "won" else -amount if outcome == "lost" else 0

    bet_repo.update_bet(bet["id"], {
        "status": outcome,
        "payout": payout,
        "profit": profit,
        "settled_at": date.today().isoformat(),
        "settlement_reason": reason,
    })

    user = user_repo.get_user(bet["user_id"])
    if not user:
        return

    if outcome == "won" and payout > 0:
        new_balance = user.get("balance", 0) + payout
        user_repo.update_user(bet["user_id"], {
            "balance": new_balance,
            "total_won": user.get("total_won", 0) + payout,
            "total_profit": user.get("total_profit", 0) + profit,
        })
        tx_repo.create_transaction({
            "user_id": bet["user_id"],
            "type": "winning",
            "amount": payout,
            "balance_after": new_balance,
            "bet_id": bet["id"],
            "game_id": game_id,
            "note": f"贏 {bet.get('market_name', '')} - {bet.get('selection', '')} @{bet.get('odds', 0)} (+{payout:,}元)",
        })
    elif outcome == "lost":
        user_repo.update_user(bet["user_id"], {
            "total_profit": user.get("total_profit", 0) + profit,
        })
    elif outcome == "refunded":
        new_balance = user.get("balance", 0) + amount
        user_repo.update_user(bet["user_id"], {"balance": new_balance})
        tx_repo.create_transaction({
            "user_id": bet["user_id"],
            "type": "refund",
            "amount": amount,
            "balance_after": new_balance,
            "bet_id": bet["id"],
            "game_id": game_id,
            "note": f"無法結算退款 {amount:,} 元",
        })


def _extract_number(text: str) -> float | None:
    match = re.search(r"[\d.]+", text)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None
