#!/bin/bash
# CloudWatch 알람 일괄 생성 스크립트
# 사전 조건: EC2 인스턴스에 IAM 역할(CloudWatchAgentServerPolicy + cloudwatch:PutMetricAlarm,
#           sns:CreateTopic, sns:Subscribe 권한) 연결 또는 aws configure 완료
# 사용법: ./setup-cloudwatch-alarms.sh <알림받을이메일>

set -e

EMAIL="${1:?사용법: $0 <알림받을이메일>}"
REGION="ap-northeast-2"
INSTANCE_ID="i-0ff6fb5fb2fa46b7b"
RDS_ID="cafeplatform"

export AWS_DEFAULT_REGION="$REGION"

echo "[1/4] SNS 토픽 생성 및 이메일 구독..."
TOPIC_ARN=$(aws sns create-topic --name server-alerts --query 'TopicArn' --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email --notification-endpoint "$EMAIL" > /dev/null
echo "  → $TOPIC_ARN (메일함에서 구독 확인(Confirm) 필요!)"

echo "[2/4] EC2 기본 알람..."
aws cloudwatch put-metric-alarm --alarm-name "EC2-SystemCheckFailed" \
  --namespace AWS/EC2 --metric-name StatusCheckFailed_System \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --statistic Maximum --period 60 --evaluation-periods 2 --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions "$TOPIC_ARN" "arn:aws:automate:${REGION}:ec2:recover"

aws cloudwatch put-metric-alarm --alarm-name "EC2-InstanceCheckFailed" \
  --namespace AWS/EC2 --metric-name StatusCheckFailed_Instance \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --statistic Maximum --period 60 --evaluation-periods 3 --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions "$TOPIC_ARN"

aws cloudwatch put-metric-alarm --alarm-name "EC2-HighCPU" \
  --namespace AWS/EC2 --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --statistic Average --period 300 --evaluation-periods 3 --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN"

echo "[3/4] 메모리/디스크/스왑 알람 (CloudWatch Agent 지표)..."
aws cloudwatch put-metric-alarm --alarm-name "EC2-HighMemory" \
  --namespace CWAgent --metric-name mem_used_percent \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --statistic Average --period 60 --evaluation-periods 3 --threshold 90 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN"

aws cloudwatch put-metric-alarm --alarm-name "EC2-HighSwap" \
  --namespace CWAgent --metric-name swap_used_percent \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID \
  --statistic Average --period 60 --evaluation-periods 3 --threshold 50 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN"

aws cloudwatch put-metric-alarm --alarm-name "EC2-HighDisk" \
  --namespace CWAgent --metric-name disk_used_percent \
  --dimensions Name=InstanceId,Value=$INSTANCE_ID Name=path,Value=/ Name=device,Value=nvme0n1p1 Name=fstype,Value=ext4 \
  --statistic Average --period 300 --evaluation-periods 2 --threshold 85 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN"

echo "[4/4] RDS 알람..."
aws cloudwatch put-metric-alarm --alarm-name "RDS-LowStorage" \
  --namespace AWS/RDS --metric-name FreeStorageSpace \
  --dimensions Name=DBInstanceIdentifier,Value=$RDS_ID \
  --statistic Average --period 300 --evaluation-periods 2 --threshold 2000000000 \
  --comparison-operator LessThanThreshold \
  --alarm-actions "$TOPIC_ARN"

aws cloudwatch put-metric-alarm --alarm-name "RDS-HighCPU" \
  --namespace AWS/RDS --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=$RDS_ID \
  --statistic Average --period 300 --evaluation-periods 3 --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN"

echo ""
echo "✅ 알람 8개 생성 완료. 이메일($EMAIL) 구독 확인을 잊지 마세요."
