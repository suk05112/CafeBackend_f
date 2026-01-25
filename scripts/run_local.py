#!/usr/bin/env python3
"""
로컬 개발 환경에서 FastAPI 서버를 실행하는 스크립트
"""
import os
import sys

# 의존성 확인
try:
    import uvicorn
except ImportError:
    print("=" * 50)
    print("❌ uvicorn이 설치되지 않았습니다.")
    print("=" * 50)
    print("다음 명령어로 의존성을 설치하세요:")
    print("  pip3 install -r requirements.txt")
    print("")
    print("또는 test_local.sh 스크립트를 사용하세요:")
    print("  ./test_local.sh")
    print("=" * 50)
    sys.exit(1)

# sudo로 실행하지 않도록 경고
if os.geteuid() == 0:
    print("=" * 50)
    print("⚠️  경고: sudo로 실행하지 마세요!")
    print("=" * 50)
    print("sudo를 사용하면 root 사용자의 Python 환경을 사용하게 되어")
    print("일반 사용자에 설치된 패키지를 찾을 수 없습니다.")
    print("")
    print("다음과 같이 실행하세요:")
    print("  python3 run_local.py")
    print("  또는")
    print("  ./test_local.sh")
    print("=" * 50)
    sys.exit(1)

if __name__ == "__main__":
    # 환경 변수 설정 (local로 설정하면 .env.local 파일 사용)
    os.environ["ENV"] = "local"
    
    # .env.local 파일 확인
    env_file = ".env.local"
    if os.path.exists(env_file):
        print(f"✅ {env_file} 파일을 사용합니다.")
    else:
        print(f"⚠️  {env_file} 파일이 없습니다. .env.dev를 사용합니다.")
        os.environ["ENV"] = "dev"  # .env.local이 없으면 dev로 폴백
    
    # uvicorn 서버 실행
    print("=" * 50)
    print("로컬 개발 서버 시작 중...")
    print("=" * 50)
    print("서버 주소: http://localhost:8000")
    print("환경: local (dev와 동일한 설정)")
    print("API 경로: http://localhost:8000/dev/")
    print("=" * 50)
    print("서버 종료: Ctrl+C")
    print("=" * 50)
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 코드 변경 시 자동 재시작
        log_level="info",
        access_log=True
    )

