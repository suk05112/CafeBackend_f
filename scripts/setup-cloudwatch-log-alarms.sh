#!/bin/bash
# nginx 404/502 로그 기반 Metric Filter + Alarm 생성 스크립트
# 사전 조건: scripts/setup-cloudwatch-alarms.sh 로 SNS 토픽(server-alerts)이 이미 생성되어 있어야 함
#           scripts/deploy-cloudwatch-agent-config.sh 로 로그 스트리밍이 이미 설정되어 있어야 함
# 사용법: ./setup-cloudwatch-log-alarms.sh

set -e

REGION="ap-northeast-2"
LOG_GROUP="gifnut-backend-system"
NAMESPACE="NginxErrors"

export AWS_DEFAULT_REGION="$REGION"

echo "[1/3] SNS 토픽(server-alerts) ARN 조회..."
TOPIC_ARN=$(aws sns list-topics --query "Topics[?ends_with(TopicArn, ':server-alerts')].TopicArn" --output text)
if [ -z "$TOPIC_ARN" ]; then
  echo "  → server-alerts 토픽을 찾을 수 없습니다. setup-cloudwatch-alarms.sh를 먼저 실행하세요."
  exit 1
fi
echo "  → $TOPIC_ARN"

echo "[2/3] Metric Filter 생성 (404 / 502)..."
aws logs put-metric-filter \
  --log-group-name "$LOG_GROUP" \
  --filter-name "nginx-404-count" \
  --filter-pattern '" 404 "' \
  --metric-transformations metricName=Count404,metricNamespace=$NAMESPACE,metricValue=1,defaultValue=0

aws logs put-metric-filter \
  --log-group-name "$LOG_GROUP" \
  --filter-name "nginx-502-count" \
  --filter-pattern '" 502 "' \
  --metric-transformations metricName=Count502,metricNamespace=$NAMESPACE,metricValue=1,defaultValue=0

echo "[3/3] Alarm 생성..."
aws cloudwatch put-metric-alarm --alarm-name "Nginx-404-Spike" \
  --namespace "$NAMESPACE" --metric-name Count404 \
  --statistic Sum --period 300 --evaluation-periods 1 --threshold 10 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$TOPIC_ARN"

aws cloudwatch put-metric-alarm --alarm-name "Nginx-502-Spike" \
  --namespace "$NAMESPACE" --metric-name Count502 \
  --statistic Sum --period 300 --evaluation-periods 1 --threshold 5 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$TOPIC_ARN"

echo ""
echo "✅ Metric Filter 2개, Alarm 2개 생성 완료 (Nginx-404-Spike, Nginx-502-Spike)."
