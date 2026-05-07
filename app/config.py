import os
import json
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LINE Bot
    line_channel_access_token: str = ""
    line_channel_secret: str = ""

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "cpbl_betting"

    # Gemini (odds generation, both steps)
    gemini_api_key: str = ""

    # OpenRouter (legacy, kept for backward-compat with old .env)
    openrouter_api_key: str = ""

    # Groq (legacy)
    groq_api_key: str = ""

    # App
    env: str = "development"
    cron_secret: str = ""  # protect cron endpoints
    public_url: str = ""  # Caddy-fronted base URL (used to build LINE image URLs)

    # Betting limits
    daily_deposit_cap: int = 10_000
    monthly_deposit_cap: int = 100_000
    daily_bet_cap: int = 10_000
    min_bet: int = 1
    bet_cutoff_minutes: int = 5

    # Odds
    overround: float = 1.08
    min_odds: float = 1.05
    max_odds: float = 15.0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
