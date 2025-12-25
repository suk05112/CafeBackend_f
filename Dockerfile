FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 curl 설치 (healthcheck용)
RUN apt-get update && \
    apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# requirements.txt 복사 및 의존성 설치
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사 (모든 파일)
COPY . .

# PYTHONPATH 설정 (app 디렉토리를 모듈로 인식)
ENV PYTHONPATH=/app

# 디버깅: 파일 구조 확인 (빌드 시 확인용, 주석 처리 가능)
# RUN ls -la /app && ls -la /app/app 2>/dev/null || echo "app directory check"

# 포트 노출
EXPOSE 8000

# 환경 변수에 따라 다른 .env 파일과 로그 레벨 사용
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--env-file", ".env.prod"]
# CMD ["uvicorn", "app.main:app",  "--reload", "--host", "0.0.0.0", "--port", "8000", "--env-file", ".env.prod", "--log-level", "debug"]
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--env-file", ".env.dev", "--log-level", "debug"]