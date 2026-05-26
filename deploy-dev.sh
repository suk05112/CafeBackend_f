#!/bin/bash

set -e

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 프로젝트 디렉토리
PROJECT_DIR="/home/ubuntu/CafeBackend"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env.dev"

echo -e "${YELLOW}=== 개발 서버 배포 시작 ===${NC}"

# 프로젝트 디렉토리로 이동
cd "$PROJECT_DIR"

# .env 파일 확인
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}❌ .env.dev 파일이 없습니다: $ENV_FILE${NC}"
    exit 1
fi

# 1. 이미지 빌드 (기존 컨테이너 유지한 채로 먼저 빌드)
echo -e "${YELLOW}[1/4] 이미지 빌드 중...${NC}"
if ! sudo docker-compose -f "$COMPOSE_FILE" build --no-cache app-dev; then
    echo -e "${RED}❌ 이미지 빌드 실패! 기존 서버는 유지됩니다.${NC}"
    exit 1
fi

# 2. 기존 컨테이너 제거
echo -e "${YELLOW}[2/4] 기존 개발 서버 컨테이너 제거 중...${NC}"
sudo docker-compose -f "$COMPOSE_FILE" stop app-dev 2>/dev/null || true
sudo docker-compose -f "$COMPOSE_FILE" rm -f app-dev 2>/dev/null || true
sudo docker rm -f app-dev 2>/dev/null || true

# 3. 컨테이너 시작
echo -e "${YELLOW}[3/4] 컨테이너 시작 중...${NC}"
if ! sudo docker-compose -f "$COMPOSE_FILE" up -d app-dev; then
    echo -e "${RED}❌ 컨테이너 시작 실패!${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" logs app-dev 2>&1 | tail -20
    exit 1
fi

# 컨테이너가 정상적으로 시작되었는지 확인
sleep 2
if ! sudo docker ps --filter "name=app-dev" --format "{{.Names}}" | grep -q "^app-dev$"; then
    echo -e "${RED}❌ 컨테이너가 시작되지 않았습니다!${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" logs app-dev 2>&1 | tail -30
    exit 1
fi

echo -e "${GREEN}✅ 개발 서버 컨테이너 시작 완료${NC}"

# 4. Health check 대기
echo -e "${YELLOW}[4/4] Health check 대기 중...${NC}"
MAX_WAIT=120
WAITED=0
HEALTHY=false

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -f http://127.0.0.1:8001/dev/health > /dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    if curl -f http://127.0.0.1:8001/health > /dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    
    echo -n "."
    sleep 3
    WAITED=$((WAITED + 3))
done

echo ""

if [ "$HEALTHY" = false ]; then
    echo -e "${RED}❌ Health check 실패!${NC}"
    echo -e "${YELLOW}컨테이너 로그 확인:${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" logs app-dev 2>&1 | tail -30
    exit 1
fi

echo -e "${GREEN}✅ Health check 통과!${NC}"

echo ""
echo -e "${GREEN}=== 개발 서버 배포 완료! ===${NC}"
echo -e "${BLUE}개발 서버 URL: https://www.502company.com/dev/${NC}"
echo ""
echo -e "${BLUE}현재 실행 중인 컨테이너:${NC}"
sudo docker ps --filter "name=app-dev" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo -e "${YELLOW}로그 확인: sudo docker logs -f app-dev${NC}"


