#!/bin/bash

# 디스크 공간 정리 스크립트
# 이 스크립트는 불필요한 캐시 파일, 로그, 임시 파일들을 정리하여 디스크 공간을 확보합니다.

set -e

echo "=========================================="
echo "디스크 공간 정리 스크립트 시작"
echo "=========================================="

# 현재 디스크 사용량 표시
echo ""
echo "[1/8] 현재 디스크 사용량 확인"
df -h / | tail -1
echo ""

# pip 캐시 정리
echo "[2/8] pip 캐시 정리 중..."
pip cache purge 2>/dev/null || echo "pip cache purge 실패 또는 사용 불가"
echo "✓ pip 캐시 정리 완료"
echo ""

# 시스템 로그 정리 (3일 이상 된 로그 삭제)
echo "[3/8] 시스템 로그 정리 중 (3일 이상 된 로그 삭제)..."
sudo journalctl --vacuum-time=3d 2>/dev/null || journalctl --vacuum-time=3d 2>/dev/null
echo "✓ 시스템 로그 정리 완료"
echo ""

# Python __pycache__ 디렉토리 정리
echo "[4/8] Python __pycache__ 디렉토리 정리 중..."
find /home/ubuntu/CafeBackend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
echo "✓ Python __pycache__ 정리 완료"
echo ""

# Python .pyc 파일 정리
echo "[5/8] Python .pyc 파일 정리 중..."
find /home/ubuntu -name "*.pyc" -delete 2>/dev/null || true
echo "✓ Python .pyc 파일 정리 완료"
echo ""

# 오래된 nginx 백업 파일 정리 (7일 이상)
echo "[6/8] 오래된 nginx 백업 파일 정리 중 (7일 이상)..."
find /tmp -name "nginx_config_backup_*" -type f -mtime +7 -delete 2>/dev/null || true
echo "✓ nginx 백업 파일 정리 완료"
echo ""

# Docker 불필요한 리소스 정리
echo "[7/8] Docker 불필요한 리소스 정리 중..."
docker system prune -f 2>/dev/null || echo "Docker 정리 실패"
docker builder prune -a -f 2>/dev/null || echo "Docker 빌드 캐시 정리 실패"
echo "✓ Docker 정리 완료"
echo ""

# 최종 디스크 사용량 표시
echo "[8/8] 최종 디스크 사용량 확인"
df -h / | tail -1
echo ""

# 정리 결과 요약
echo "=========================================="
echo "디스크 공간 정리 완료!"
echo "=========================================="
echo ""
echo "정리된 항목:"
echo "  - pip 캐시"
echo "  - 시스템 로그 (3일 이상)"
echo "  - Python __pycache__ 및 .pyc 파일"
echo "  - 오래된 nginx 백업 파일 (7일 이상)"
echo "  - Docker 불필요한 리소스"
echo ""
echo "추가 정리가 필요한 경우:"
echo "  - Manager/venv 디렉토리 확인: du -sh ~/Manager/venv"
echo "  - 큰 파일 찾기: find ~ -type f -size +100M"
echo ""

