"""Odds engine: uses OpenRouter LLM to generate dynamic betting markets."""
from __future__ import annotations

import json
import logging
import time

from openai import OpenAI

from app.config import settings
from app.betting.odds_prompt import build_odds_prompt
from app.betting.odds_fallback import generate_fallback_odds

logger = logging.getLogger(__name__)

MAX_RETRIES = 6

# Models to try in order (rotate on failure)
MODELS = [
    "meta-llama/llama-4-maverick:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3-235b-a22b:free",
    "deepseek/deepseek-chat-v3-0324:free",
]


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
        logger.error(f"All LLM attempts failed, falling back to rule-based: {e}")
        return _generate_with_fallback(games, standings)


def _parse_json_response(response_text: str) -> list[dict]:
    """Extract and parse JSON from LLM response. Raises on failure."""
    text = response_text.strip()

    # Remove thinking tags (DeepSeek R1)
    if "<think>" in text:
        think_end = text.rfind("</think>")
        if think_end != -1:
            text = text[think_end + 8:].strip()

    # Extract from code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # Try to find JSON array if there's garbage before/after
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start:end + 1]

    return json.loads(text)


def _generate_with_llm(games: list[dict], standings: dict) -> dict[str, dict]:
    system_prompt, user_prompt = build_odds_prompt(games, standings)
    client = _get_client()

    last_error = None
    for attempt in range(MAX_RETRIES):
        model = MODELS[attempt % len(MODELS)]
        try:
            logger.info(f"LLM attempt {attempt + 1}/{MAX_RETRIES} with {model}")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_tokens=4096,
            )

            response_text = response.choices[0].message.content or ""
            odds_list = _parse_json_response(response_text)

            # Validate structure
            if not isinstance(odds_list, list) or len(odds_list) == 0:
                raise ValueError("Empty or invalid response")

            # Build result
            result = {}
            for game_odds in odds_list:
                game_id = game_odds.get("game_id", "")
                markets = game_odds.get("markets", [])
                validated_markets = _validate_markets(markets)
                if validated_markets:
                    result[game_id] = {"markets": validated_markets}

            if not result:
                raise ValueError("No valid markets generated")

            # Fallback for missing games
            for game in games:
                gid = game.get("id", "")
                if gid not in result:
                    logger.warning(f"No LLM odds for game {gid}, using fallback")
                    result[gid] = generate_fallback_odds(game, standings)

            logger.info(f"LLM success on attempt {attempt + 1} with {model}")
            return result

        except Exception as e:
            last_error = e
            logger.warning(f"LLM attempt {attempt + 1} failed ({model}): {e}")
            time.sleep(1)

    raise RuntimeError(f"All {MAX_RETRIES} LLM attempts failed. Last error: {last_error}")


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
            if not isinstance(odds, (int, float)) or odds <= 0:
                continue
            if odds < settings.min_odds:
                odds = settings.min_odds
            elif odds > settings.max_odds:
                odds = settings.max_odds
            opt["odds"] = round(odds, 2)
            valid_options.append(opt)

        if len(valid_options) < 2:
            continue

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
