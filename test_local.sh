#!/bin/bash

set -e

echo "=========================================="
echo "로컬 테스트 환경 설정"
echo "=========================================="

# 프로젝트 디렉토리로 이동
cd /home/ubuntu/CafeBackend

# 환경 변수 확인
if [ ! -f ".env.local" ]; then
    echo "⚠️  .env.local 파일이 없습니다. .env.dev를 복사합니다..."
    cp .env.dev .env.local
fi

# Python 가상 환경 확인 (선택사항)
if [ -d "venv" ]; then
    echo "✅ 가상 환경 발견, 활성화 중..."
    source venv/bin/activate
fi

# 의존성 확인
echo ""
echo "[1/3] 의존성 확인 중..."
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "⚠️  FastAPI가 설치되지 않았습니다. 설치 중..."
    pip3 install -r requirements.txt
else
    echo "✅ 의존성 확인 완료"
fi

# 데이터베이스 연결 테스트
echo ""
echo "[2/3] 데이터베이스 연결 테스트 중..."
if python3 -c "
import sys
sys.path.insert(0, '.')
from db.session import get_db_connection
try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1')
    cursor.fetchone()
    cursor.close()
    conn.close()
    print('✅ 데이터베이스 연결 성공!')
except Exception as e:
    print(f'❌ 데이터베이스 연결 실패: {e}')
    sys.exit(1)
"; then
    echo "✅ 데이터베이스 연결 확인 완료"
else
    echo "❌ 데이터베이스 연결 실패"
    exit 1
fi

# 서버 실행
echo ""
echo "[3/3] FastAPI 서버 시작 중..."
echo "=========================================="
echo "서버 주소: http://localhost:8000"
echo "개발 환경: dev"
echo "API 경로: http://localhost:8000/dev/"
echo "=========================================="
echo "서버 종료: Ctrl+C"
echo "=========================================="
echo ""

# 서버 실행
python3 run_local.py


