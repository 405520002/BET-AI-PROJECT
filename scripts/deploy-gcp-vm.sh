#!/bin/bash
# ============================================================
# CPBL Betting Bot - GCP VM 部署腳本
#
# 使用方式:
#   1. 先在本地設好 gcloud: gcloud auth login
#   2. 設定專案: gcloud config set project YOUR_PROJECT_ID
#   3. 執行: bash scripts/deploy-gcp-vm.sh
# ============================================================

set -e

# === 設定 ===
VM_NAME="cpbl-bot"
ZONE="us-west1-b"           # 免費 tier 區域
MACHINE_TYPE="e2-micro"     # 免費 tier 機型
IMAGE_FAMILY="ubuntu-2204-lts"
IMAGE_PROJECT="ubuntu-os-cloud"

echo "=== Step 1: 建立 GCP VM ==="
gcloud compute instances create $VM_NAME \
  --zone=$ZONE \
  --machine-type=$MACHINE_TYPE \
  --image-family=$IMAGE_FAMILY \
  --image-project=$IMAGE_PROJECT \
  --boot-disk-size=30GB \
  --tags=http-server,https-server \
  --metadata=startup-script='#!/bin/bash
    # Install Docker
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    # Install Docker Compose
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
  '

echo "=== Step 2: 開放 8080 port ==="
gcloud compute firewall-rules create allow-bot-8080 \
  --allow=tcp:8080 \
  --target-tags=http-server \
  --description="Allow CPBL bot traffic" \
  2>/dev/null || echo "Firewall rule already exists"

echo "=== Step 3: 等待 VM 啟動 ==="
sleep 30

echo "=== Step 4: 取得 VM IP ==="
VM_IP=$(gcloud compute instances describe $VM_NAME --zone=$ZONE --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo "VM IP: $VM_IP"

echo ""
echo "============================================================"
echo "VM 建好了！接下來手動操作："
echo ""
echo "1. SSH 進 VM:"
echo "   gcloud compute ssh $VM_NAME --zone=$ZONE"
echo ""
echo "2. 在 VM 裡 clone 你的 repo 或上傳檔案:"
echo "   git clone <your-repo-url>"
echo "   cd AI-experiment"
echo ""
echo "3. 建立 .env 檔案 (把你的 keys 填進去)"
echo ""
echo "4. 啟動:"
echo "   docker compose up -d"
echo ""
echo "5. 設定 LINE Webhook URL:"
echo "   http://$VM_IP:8080/webhook"
echo ""
echo "6. 設定 crontab 排程 (在 VM 裡):"
echo "   crontab -e"
echo "   加入:"
echo "   0 8 * * * curl -s -X POST http://localhost:8080/cron/scrape-schedule"
echo "   30 22 * * * curl -s -X POST http://localhost:8080/cron/scrape-results"
echo "   0 0 * * * curl -s -X POST http://localhost:8080/cron/settle"
echo "============================================================"
