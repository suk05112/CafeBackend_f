#!/bin/bash
# CloudWatch Agent 설정(로그 수집 포함) 서버 반영 스크립트
# 서버(EC2)에서 실행: cd /home/ubuntu/CafeBackend && ./scripts/deploy-cloudwatch-agent-config.sh

set -e

PROJECT_DIR="/home/ubuntu/CafeBackend"
CONFIG_SRC="$PROJECT_DIR/deploy/cloudwatch-agent-config.json"
CONFIG_DST="/opt/aws/amazon-cloudwatch-agent/etc/config.json"

if [ ! -f "$CONFIG_SRC" ]; then
  echo "설정 파일이 없습니다: $CONFIG_SRC"
  exit 1
fi

echo "[1/2] CloudWatch Agent 설정 반영..."
sudo cp "$CONFIG_SRC" "$CONFIG_DST"

echo "[2/2] CloudWatch Agent 재시작 (fetch-config)..."
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s -c "file:$CONFIG_DST"

echo ""
echo "✅ 완료. 상태 확인: sudo systemctl status amazon-cloudwatch-agent"
echo "   로그 유입 확인: AWS 콘솔 > CloudWatch Logs > gifnut-backend-system 로그 그룹"
