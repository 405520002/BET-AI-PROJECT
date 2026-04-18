#!/bin/bash
# Usage: run_cron.sh <endpoint> <label>
# Example: run_cron.sh /cron/morning "08:00 早晨排程"

ENDPOINT=$1
LABEL=$2
CRON_URL="https://cpbl-bet.duckdns.org"
CRON_SECRET="cpbl-cron-2026-secret"
LINE_TOKEN="dFNzpYYQhz0LOX7OJd6kyA0NZqNFgNO+lFXey5tcBDXGySxKQPNcMla0KESQuBSGUpCSR2x1q1S1cfzpT625GLvPoximQkqGnjT4JJPLoDeTOAU69RhnmCw2RJ0m67CNvokdKUCXmwTDW7X/BasNCgdB04t89/1O/w1cDnyilFU="
ADMIN_USER="Ud5116f87cb190fdb89ba41c7e36bcf65"

# Run the cron endpoint
RESULT=$(curl -s --connect-timeout 10 --max-time 300 -w "\n%{http_code}" \
  -X POST "${CRON_URL}${ENDPOINT}" \
  -H "X-Cron-Secret: ${CRON_SECRET}" 2>&1)

HTTP_CODE=$(echo "$RESULT" | tail -1)
BODY=$(echo "$RESULT" | head -n -1)

# Log
echo "[$(date)] ${LABEL}: HTTP ${HTTP_CODE} ${BODY}" >> /tmp/cron.log

# If failed (non-200 or empty), alert admin via LINE
if [ "$HTTP_CODE" != "200" ] || [ -z "$BODY" ]; then
  MSG="⚠️ ${LABEL} 排程異常\nHTTP: ${HTTP_CODE}\n${BODY:0:200}"
  curl -s -X POST https://api.line.me/v2/bot/message/push \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${LINE_TOKEN}" \
    -d "{\"to\":\"${ADMIN_USER}\",\"messages\":[{\"type\":\"text\",\"text\":\"${MSG}\"}]}" \
    > /dev/null 2>&1
fi
