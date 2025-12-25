#!/bin/bash
# 개발 서버 재배포 스크립트

cd /home/ubuntu/CafeBackend

# 기존 컨테이너 완전 제거
sudo docker-compose stop app-dev
sudo docker-compose rm -f app-dev
sudo docker rm -f app-dev 2>/dev/null || true

# 재빌드 및 시작
sudo docker-compose build app-dev
sudo docker-compose up -d app-dev

# 컨테이너 시작 확인
sleep 3
if sudo docker ps | grep -q app-dev; then
    echo "✅ 개발 서버 배포 완료"
    echo "로그 확인: sudo docker logs -f app-dev"
else
    echo "❌ 개발 서버 시작 실패"
    echo "로그 확인: sudo docker logs app-dev"
    exit 1
fi

