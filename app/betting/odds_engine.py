"""Odds engine: uses OpenRouter (DeepSeek R1) to generate dynamic betting markets."""
from __future__ import annotations

import json
import logging

from openai import OpenAI

from app.config import settings
from app.betting.odds_prompt import build_odds_prompt
from app.betting.odds_fallback import generate_fallback_odds

logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def generate_odds_for_games(games: list[dict], standings: dict) -> dict[str, dict]:
    if not games:
        return {}

    try:
        return _generate_with_llm(games, standings)
    except Exception as e:
        logger.error(f"OpenRouter API failed, falling back to rule-based: {e}")
        return _generate_with_fallback(games, standings)


def _generate_with_llm(games: list[dict], standings: dict) -> dict[str, dict]:
    system_prompt, user_prompt = build_odds_prompt(games, standings)

    client = _get_client()

    response = client.chat.completions.create(
        model="nvidia/nemotron-3-super-120b-a12b:free",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    response_text = response.choices[0].message.content.strip()

    # Extract JSON from response
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()

    odds_list = json.loads(response_text)

    # Validate and build result
    result = {}
    for game_odds in odds_list:
        game_id = game_odds.get("game_id", "")
        markets = game_odds.get("markets", [])

        validated_markets = _validate_markets(markets)
        if validated_markets:
            result[game_id] = {"markets": validated_markets}

    # Fallback for missing games
    for game in games:
        gid = game.get("id", "")
        if gid not in result:
            logger.warning(f"No LLM odds for game {gid}, using fallback")
            result[gid] = generate_fallback_odds(game, standings)

    return result


def _generate_with_fallback(games: list[dict], standings: dict) -> dict[str, dict]:
    result = {}
    for game in games:
        gid = game.get("id", "")
        result[gid] = generate_fallback_odds(game, standings)
    return result


def _validate_markets(markets: list[dict]) -> list[dict]:
    validated = []

    for market in markets:
        options = market.get("options", [])
        if len(options) < 2:
            continue

        valid_options = []
        for opt in options:
            odds = opt.get("odds", 0)
            if odds < settings.min_odds:
                odds = settings.min_odds
            elif odds > settings.max_odds:
                odds = settings.max_odds
            opt["odds"] = round(odds, 2)
            valid_options.append(opt)

        implied_sum = sum(1.0 / opt["odds"] for opt in valid_options)
        if implied_sum < 1.02:
            logger.warning(f"Market '{market.get('name')}' overround too low ({implied_sum:.3f}), adjusting")
            factor = 1.08 / implied_sum
            for opt in valid_options:
                opt["odds"] = round(max(settings.min_odds, opt["odds"] / factor), 2)
        elif implied_sum > 1.20:
            logger.warning(f"Market '{market.get('name')}' overround too high ({implied_sum:.3f}), adjusting")
            factor = 1.08 / implied_sum
            for opt in valid_options:
                opt["odds"] = round(min(settings.max_odds, opt["odds"] / factor), 2)

        market["options"] = valid_options
        validated.append(market)

    return validated
