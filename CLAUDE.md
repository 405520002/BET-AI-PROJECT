# CLAUDE.md

CPBL Betting Bot — LINE bot that pushes daily CPBL game cards, AI-generated odds, and bet settlement.

## Stack
- **App**: FastAPI + uvicorn (`app/main.py`)
- **Scrapers**: httpx async, target `https://www.cpbl.com.tw` (en.cpbl is permanently 500ing as of 2026-04)
- **Bot**: line-bot-sdk v3
- **DB**: MongoDB 7 (running in same docker-compose)
- **AI**: OpenRouter (DeepSeek R1 primary), Groq fallback
- **Scheduler**: APScheduler in-process + cron-driven HTTP endpoints
- **Deploy**: GCP free-tier e2-micro VM (`cpbl-bot` in `us-west1-b`), docker-compose, Caddy reverse-proxy fronts on `cpbl-bet.duckdns.org`

## Layout
```
app/
  main.py                # FastAPI entry, cron endpoints (/cron/morning|midday|settle|notify|weekly-awards)
  line_bot/handler.py    # All LINE webhook handlers (live scores, bets, etc.)
  scraper/               # CPBL HTML/JSON scrapers
    http_client.py       # Shared httpx client + token regex
    cpbl_schedule.py     # Schedule/today's games + EN→ZH passthrough helpers
    cpbl_boxscore.py     # Per-game box scores
    cpbl_standings.py    # Season standings
    cpbl_results.py      # Final scores (uses schedule API, status filter)
  scheduler/             # APScheduler jobs (morning_job, midday_update, midnight_settle, weekly_awards)
  betting/               # odds_engine.py, settlement.py
scripts/
  deploy-gcp-vm.sh       # GCP VM provisioning
  setup-vm.sh            # Inside-VM bootstrap
  scrape_player_names.py # One-shot: build player_names.json
```

## Running locally
- Two virtualenvs exist (`.venv/`, `venv/`). Pick `.venv/` — it's what recent sessions used.
- `source .env && .venv/bin/python -c "..."`  for ad-hoc scraper runs
- No proper test suite. Verification = run scraper functions directly and inspect output.

## Conventions
- All scrapers use `app/scraper/http_client.py:fetch_api()` for tokenized POSTs and `fetch_html()` for plain GETs.
- Token regex must include both forms (JS: `RequestVerificationToken: 'xxx'`, HTML: `<input name="__RequestVerificationToken" value="xxx" />`). Async `fetch_api` was missing the HTML fallback until 2026-04 — verify both before changing.
- Drop `br` from `Accept-Encoding`. httpx does not decompress brotli without the `brotli` package; including `br` causes opaque parse failures.
- Cron endpoints require `X-Cron-Secret` header equal to `settings.cron_secret` in production. Dev mode (`ENV=development`) skips auth.
- Commits are by feature scope, not per-task. The harness `commit_after_each_task: false` is the project default.

## Deploy
- VM has `Caddyfile` + custom `docker-compose.yml` as **uncommitted local-only** files (production reverse-proxy + mongo bind-to-localhost). Preserve via `git stash` + `git checkout -- <stale dups>` + `git stash pop` on every harness deploy. Never `git reset --hard` on the VM.
- Project dir on VM: `/home/wadesu/BET-AI-PROJECT`
- `sudo docker compose up -d --build` from project dir; `app:8080` is internal-only (Caddy-fronted).
- Health check from host: `docker compose exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/health').read().decode())"` (curl is not installed in the app image).

## CPBL site quirks
- `www.cpbl.com.tw` is fronted by HiNet CDN (`www-cpbl.cdn.hinet.net`, IPs 203.74.x.x).
- **Path-level geo-block from non-TW IPs**: `/` returns 200, but `/schedule` and `/standings/season` return 404 from US-region GCP VM. UA / Referer / cookies do not help. The cron job runs but scrapes 0 rows in production.
- The fix is a **TW-IP proxy**. Two scaffolded options exist in git history (deleted in commit `faf3826`): `cf-proxy/` (Cloudflare Worker, smart-placement) and `gcp-proxy/` (Cloud Function in asia-east1).
