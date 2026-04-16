# CPBL Virtual Betting LINE Bot

中華職棒虛擬下注 LINE Bot - 使用 AI 動態生成賠率的虛擬投注平台

## Features

- 查看當日 CPBL 賽事 (球場、先發投手)
- AI 動態生成下注玩法和賠率 (Claude API)
- 虛擬幣儲值和下注
- 獲利排行榜、個人戰績
- 每日自動結算

## Tech Stack

- FastAPI + LINE Bot SDK v3
- Firebase Firestore
- Claude API (Haiku) for odds generation
- Google Cloud Run + Cloud Scheduler

## Setup

### 1. LINE Bot

1. 到 [LINE Developers](https://developers.line.biz) 建立 Provider
2. 建立 Messaging API Channel
3. 取得 **Channel Access Token** 和 **Channel Secret**
4. Webhook URL 設定為 `https://<your-domain>/webhook`
5. 開啟 "Use webhook"，關閉 "Auto-reply messages"

### 2. Firebase

1. 到 [Firebase Console](https://console.firebase.google.com) 建立專案
2. 啟用 **Firestore Database** (production mode)
3. 到 Project Settings > Service Accounts > **Generate new private key**
4. 將 JSON 內容設為環境變數 `FIREBASE_CREDENTIALS`

### 3. Anthropic API

1. 到 [Anthropic Console](https://console.anthropic.com) 取得 API Key
2. 設為環境變數 `ANTHROPIC_API_KEY`

### 4. Local Development

```bash
# 建立虛擬環境
python -m venv .venv
source .venv/bin/activate

# 安裝依賴
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入你的 keys

# 啟動
uvicorn app.main:app --reload --port 8080

# 用 ngrok 暴露 webhook
ngrok http 8080
```

### 5. Deploy to Cloud Run

```bash
# 登入 GCP
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 部署
gcloud run deploy cpbl-bet-bot \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars "LINE_CHANNEL_ACCESS_TOKEN=xxx,LINE_CHANNEL_SECRET=xxx,ANTHROPIC_API_KEY=xxx,CRON_SECRET=xxx,ENV=production"

# 設定 Cloud Scheduler
gcloud scheduler jobs create http scrape-schedule \
  --schedule="0 8 * * *" \
  --uri="https://YOUR_CLOUD_RUN_URL/cron/scrape-schedule" \
  --http-method=POST \
  --headers="X-Cron-Secret=xxx" \
  --time-zone="Asia/Taipei"

gcloud scheduler jobs create http scrape-results \
  --schedule="30 22 * * *" \
  --uri="https://YOUR_CLOUD_RUN_URL/cron/scrape-results" \
  --http-method=POST \
  --headers="X-Cron-Secret=xxx" \
  --time-zone="Asia/Taipei"

gcloud scheduler jobs create http settle \
  --schedule="0 0 * * *" \
  --uri="https://YOUR_CLOUD_RUN_URL/cron/settle" \
  --http-method=POST \
  --headers="X-Cron-Secret=xxx" \
  --time-zone="Asia/Taipei"
```

## LINE Bot Commands

| 指令 | 功能 |
|------|------|
| 今日賽事 | 查看今天的比賽和下注盤口 |
| 儲值 | 儲值虛擬幣 |
| 我的戰績 | 餘額、勝率、獲利 |
| 排行榜 | 獲利 TOP 10 + 莊家獲利 |
| 我的注單 | 最近下注紀錄 |
| 說明 | 使用說明 |

## Rules

- 儲值上限: 每日 10,000 / 30天 100,000
- 下注上限: 每日 10,000，最低 1 元
- 餘額不足不能下注
- 延賽全額退款
- 每日午夜自動結算
