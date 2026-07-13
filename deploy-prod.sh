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
STATE_FILE="$PROJECT_DIR/.deployment_state"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env.prod"

echo -e "${YELLOW}=== 운영 서버 무중단 배포 시작 ===${NC}"

# 프로젝트 디렉토리로 이동
cd "$PROJECT_DIR"

# .env 파일 확인
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}❌ .env.prod 파일이 없습니다: $ENV_FILE${NC}"
    exit 1
fi

# 현재 활성 환경 확인
detect_current_env() {
    if [ -f "$STATE_FILE" ]; then
        CURRENT_ENV=$(cat "$STATE_FILE" | tr -d '\n')
        if [ "$CURRENT_ENV" = "green" ] || [ "$CURRENT_ENV" = "blue" ]; then
            echo "$CURRENT_ENV"
            return
        fi
    fi
    
    GREEN_RUNNING=$(sudo docker ps --filter "name=green" --filter "status=running" --format "{{.Names}}" | head -1)
    BLUE_RUNNING=$(sudo docker ps --filter "name=blue" --filter "status=running" --format "{{.Names}}" | head -1)
    
    if [ -n "$GREEN_RUNNING" ] && [ -z "$BLUE_RUNNING" ]; then
        echo "green"
    elif [ -n "$BLUE_RUNNING" ] && [ -z "$GREEN_RUNNING" ]; then
        echo "blue"
    elif [ -n "$GREEN_RUNNING" ] && [ -n "$BLUE_RUNNING" ]; then
        GREEN_STARTED=$(sudo docker inspect --format='{{.State.StartedAt}}' green 2>/dev/null || echo "1970-01-01T00:00:00Z")
        BLUE_STARTED=$(sudo docker inspect --format='{{.State.StartedAt}}' blue 2>/dev/null || echo "1970-01-01T00:00:00Z")
        
        if [ "$GREEN_STARTED" \> "$BLUE_STARTED" ]; then
            echo "green"
        else
            echo "blue"
        fi
    else
        echo "blue"
    fi
}

# 현재 환경 감지
CURRENT_ENV=$(detect_current_env)

# 새 환경 결정
if [ "$CURRENT_ENV" = "green" ]; then
    NEW_ENV="blue"
    CURRENT_PORT=8000
    NEW_PORT=8002
else
    NEW_ENV="green"
    CURRENT_PORT=8002
    NEW_PORT=8000
fi

echo -e "${BLUE}현재 활성 환경: ${CURRENT_ENV} (포트: ${CURRENT_PORT})${NC}"
echo -e "${GREEN}새 환경 배포: ${NEW_ENV} (포트: ${NEW_PORT})${NC}"

# 1. 새 환경 빌드 및 시작
echo -e "${YELLOW}[1/5] 새 ${NEW_ENV} 환경 빌드 및 시작 중...${NC}"

# 기존 컨테이너가 있다면 완전히 제거
if sudo docker ps -a --filter "name=$NEW_ENV" --format "{{.Names}}" | grep -q "^${NEW_ENV}$"; then
    echo -e "${YELLOW}기존 ${NEW_ENV} 컨테이너 제거 중...${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" stop "$NEW_ENV" 2>/dev/null || true
    sudo docker-compose -f "$COMPOSE_FILE" rm -f "$NEW_ENV" 2>/dev/null || true
    sudo docker rm -f "$NEW_ENV" 2>/dev/null || true
fi

# 이미지 준비 (DEPLOY_IMAGE 지정 시 레지스트리에서 풀 — 서버 빌드 없음)
if [ -n "$DEPLOY_IMAGE" ]; then
    echo -e "${YELLOW}레지스트리 이미지 풀 중: ${DEPLOY_IMAGE}${NC}"
    sudo docker pull "$DEPLOY_IMAGE"
    sudo docker tag "$DEPLOY_IMAGE" "cafebackend_${NEW_ENV}:latest"
else
    echo -e "${YELLOW}이미지 빌드 중...${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" build "$NEW_ENV"
fi

# 컨테이너 시작
echo -e "${YELLOW}컨테이너 시작 중...${NC}"
if ! sudo docker-compose -f "$COMPOSE_FILE" up -d --force-recreate "$NEW_ENV"; then
    echo -e "${RED}❌ 컨테이너 시작 실패!${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" logs "$NEW_ENV" 2>&1 | tail -20
    exit 1
fi

# 컨테이너가 정상적으로 시작되었는지 확인
sleep 2
if ! sudo docker ps --filter "name=$NEW_ENV" --format "{{.Names}}" | grep -q "^${NEW_ENV}$"; then
    echo -e "${RED}❌ 컨테이너가 시작되지 않았습니다!${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" logs "$NEW_ENV" 2>&1 | tail -30
    exit 1
fi

echo -e "${GREEN}✅ ${NEW_ENV} 컨테이너 시작 완료${NC}"

# 2. Health check 대기
echo -e "${YELLOW}[2/5] Health check 대기 중...${NC}"
MAX_WAIT=120
WAITED=0
HEALTHY=false

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -f http://127.0.0.1:${NEW_PORT}/prod/health > /dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    if curl -f http://127.0.0.1:${NEW_PORT}/health > /dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    
    echo -n "."
    sleep 3
    WAITED=$((WAITED + 3))
done

echo ""

if [ "$HEALTHY" = false ]; then
    echo -e "${RED}❌ Health check 실패! 배포 중단 및 롤백.${NC}"
    sudo docker-compose -f "$COMPOSE_FILE" logs "$NEW_ENV" 2>&1 | tail -30
    sudo docker-compose -f "$COMPOSE_FILE" stop "$NEW_ENV" 2>/dev/null || true
    sudo docker-compose -f "$COMPOSE_FILE" rm -f "$NEW_ENV" 2>/dev/null || true
    sudo docker rm -f "$NEW_ENV" 2>/dev/null || true
    exit 1
fi

echo -e "${GREEN}✅ Health check 통과!${NC}"

# 3. Nginx 설정 업데이트 (새 포트를 기본으로)
echo -e "${YELLOW}[3/5] Nginx 설정 업데이트 중...${NC}"

NGINX_CONFIG="/etc/nginx/sites-available/502company"
NGINX_CONFIG_BACKUP="/tmp/nginx_config_backup_$(date +%Y%m%d_%H%M%S)"

# Nginx 설정 백업
if [ -f "$NGINX_CONFIG" ]; then
    sudo cp "$NGINX_CONFIG" "$NGINX_CONFIG_BACKUP" 2>/dev/null || true
    echo -e "${BLUE}Nginx 설정 백업: $NGINX_CONFIG_BACKUP${NC}"
fi

# Nginx 설정에서 api_prod upstream의 기본 포트를 새 포트로 변경
sudo sed -i "s/server 127.0.0.1:\(8000\|8002\);/server 127.0.0.1:${NEW_PORT};/" "$NGINX_CONFIG"
sudo sed -i "s/server 127.0.0.1:\(8000\|8002\) backup;/server 127.0.0.1:${CURRENT_PORT} backup;/" "$NGINX_CONFIG"

# Nginx 설정 테스트
if ! sudo nginx -t; then
    echo -e "${RED}❌ Nginx 설정 오류! 롤백 중...${NC}"
    if [ -f "$NGINX_CONFIG_BACKUP" ]; then
        sudo cp "$NGINX_CONFIG_BACKUP" "$NGINX_CONFIG"
        sudo nginx -t && sudo nginx -s reload
    fi
    sudo docker-compose -f "$COMPOSE_FILE" stop "$NEW_ENV" 2>/dev/null || true
    exit 1
fi

# Nginx reload
if sudo nginx -s reload; then
    echo -e "${GREEN}✅ Nginx reload 완료${NC}"
    sleep 2
    if ! sudo systemctl is-active --quiet nginx; then
        echo -e "${RED}❌ Nginx가 실행 중이 아닙니다! 롤백 시도...${NC}"
        if [ -f "$NGINX_CONFIG_BACKUP" ]; then
            sudo cp "$NGINX_CONFIG_BACKUP" "$NGINX_CONFIG"
            sudo nginx -t && sudo nginx -s reload
        fi
        sudo docker-compose -f "$COMPOSE_FILE" stop "$NEW_ENV" 2>/dev/null || true
        exit 1
    fi
else
    echo -e "${RED}❌ Nginx reload 실패! 롤백 중...${NC}"
    if [ -f "$NGINX_CONFIG_BACKUP" ]; then
        sudo cp "$NGINX_CONFIG_BACKUP" "$NGINX_CONFIG"
        sudo nginx -t && sudo nginx -s reload
    fi
    sudo docker-compose -f "$COMPOSE_FILE" stop "$NEW_ENV" 2>/dev/null || true
    exit 1
fi

# 4. 트래픽 전환 대기
echo -e "${YELLOW}[4/5] 트래픽 전환 대기 중 (10초)...${NC}"
sleep 10

# 5. 기존 환경 중지
echo -e "${YELLOW}[5/5] 기존 ${CURRENT_ENV} 환경 중지 중...${NC}"
sudo docker-compose -f "$COMPOSE_FILE" stop "$CURRENT_ENV"

# 상태 파일 업데이트
echo "$NEW_ENV" > "$STATE_FILE"
echo -e "${GREEN}✅ 상태 파일 업데이트: $NEW_ENV${NC}"

echo ""
echo -e "${GREEN}=== 운영 서버 배포 완료! ===${NC}"
echo -e "${GREEN}새 활성 환경: ${NEW_ENV} (포트: ${NEW_PORT})${NC}"
echo -e "${YELLOW}다음 배포 시 ${CURRENT_ENV} 환경이 사용됩니다.${NC}"
echo ""
echo -e "${BLUE}현재 실행 중인 컨테이너:${NC}"
sudo docker ps --filter "name=green" --filter "name=blue" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"


