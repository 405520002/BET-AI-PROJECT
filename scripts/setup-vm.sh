#!/bin/bash
# ============================================================
# VM 內部快速設定腳本
# SSH 進 VM 後執行: bash scripts/setup-vm.sh
# ============================================================

set -e

echo "=== 建立 .env ==="
if [ ! -f .env ]; then
cat > .env << 'ENVEOF'
# LINE Bot
LINE_CHANNEL_ACCESS_TOKEN=填你的token
LINE_CHANNEL_SECRET=填你的secret

# MongoDB
MONGODB_URI=mongodb://mongo:27017
MONGODB_DB=cpbl_betting

# Groq (免費 backup)
GROQ_API_KEY=填你的key

# OpenRouter (DeepSeek R1)
OPENROUTER_API_KEY=填你的key

# App
ENV=production
CRON_SECRET=填一個隨機字串
ENVEOF
echo ".env 已建立，請編輯填入你的 keys: nano .env"
else
echo ".env 已存在"
fi

echo ""
echo "=== 啟動 Docker Compose ==="
sudo docker compose up -d

echo ""
echo "=== 檢查狀態 ==="
sudo docker compose ps
curl -s http://localhost:8080/health

echo ""
echo "=== 設定 Crontab ==="
(crontab -l 2>/dev/null; echo "0 8 * * * curl -s -X POST http://localhost:8080/cron/scrape-schedule > /dev/null 2>&1") | sort -u | crontab -
(crontab -l 2>/dev/null; echo "30 22 * * * curl -s -X POST http://localhost:8080/cron/scrape-results > /dev/null 2>&1") | sort -u | crontab -
(crontab -l 2>/dev/null; echo "0 0 * * * curl -s -X POST http://localhost:8080/cron/settle > /dev/null 2>&1") | sort -u | crontab -
echo "Crontab 已設定:"
crontab -l

echo ""
echo "============================================================"
echo "完成！"
echo "LINE Webhook URL: http://$(curl -s ifconfig.me):8080/webhook"
echo "============================================================"
