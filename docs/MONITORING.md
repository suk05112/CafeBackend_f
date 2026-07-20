# 서버 오류 모니터링 (CloudWatch → Slack)

nginx 502/404 등 오류를 CloudWatch로 실시간 감지하고 Slack으로 알림을 받기 위한 구성.

## 구성 개요

```
nginx 로그 (access.log / error.log)
  → CloudWatch Agent (로그 스트리밍)
  → CloudWatch Logs (로그 그룹: gifnut-backend-system)
  → Metric Filter (404 / 502 카운트)
  → CloudWatch Alarm
  → SNS (server-alerts 토픽)
  → AWS Chatbot
  → Slack (#server-error-alert)
```

## 서버 반영 절차

EC2 서버(`/home/ubuntu/CafeBackend`)에서 순서대로 실행:

```bash
# 1. 로그 수집 설정 반영 (CloudWatch Agent)
./scripts/deploy-cloudwatch-agent-config.sh

# 2. SNS 토픽 및 인프라 알람 생성 (최초 1회, 이미 되어 있다면 생략)
./scripts/setup-cloudwatch-alarms.sh <알림받을이메일>

# 3. nginx 로그 기반 Metric Filter + Alarm 생성
./scripts/setup-cloudwatch-log-alarms.sh
```

## Slack 연동 설정 (AWS 콘솔, 수동)

이 부분은 Slack 워크스페이스 관리자 권한과 AWS 콘솔 접근이 필요해 코드/스크립트로 자동화하지 않음.

1. Slack에서 `#server-error-alert` 채널 생성
2. AWS 콘솔 → **AWS Chatbot** → Slack 워크스페이스 연동(인증)
3. Chatbot에서 새 채널 구성 생성 → `#server-error-alert` 채널 선택
4. 알림받을 SNS 토픽으로 기존 `server-alerts` 토픽 선택(구독 추가)
5. IAM 역할은 Chatbot 마법사가 제안하는 기본 정책(CloudWatch 읽기 권한) 그대로 사용

연동 후 테스트 알람을 한번 트리거해 `#server-error-alert` 채널에 메시지가 오는지 확인.

## 확인된 로그 파일 경로 (2026-07-20 dev 서버 기준)

- `/var/log/nginx/502company_access.log` — combined 포맷, HTTP 상태 코드 포함 (404/502 감지 대상)
- `/var/log/nginx/502company_error.log` — nginx 내부 에러(upstream 연결 실패 등), 상태 코드 없음

## 알람 임계치

| 알람명 | 조건 | 대상 |
|---|---|---|
| `Nginx-404-Spike` | 5분간 404 응답 10회 이상 | server-alerts (SNS) |
| `Nginx-502-Spike` | 5분간 502 응답 5회 이상 | server-alerts (SNS) |

필요 시 `scripts/setup-cloudwatch-log-alarms.sh`의 `--threshold` 값을 조정 후 재실행(같은 이름의 alarm은 덮어씀).

## 스코프 제외

CloudWatch Synthetics Canary(엔드포인트 주기적 헬스체크)는 이번 작업 범위에서 제외. 별도 티켓으로 진행 필요 시 논의.
