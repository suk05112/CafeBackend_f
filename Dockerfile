FROM python:3.10-slim

WORKDIR /app


# 필요한 파일 복사
COPY requirements.txt .

# 패키지 설치
# RUN apt-get update && apt-get install -y gcc
RUN pip install --upgrade pip && pip install -r requirements.txt
RUN pip install pydantic

# RUN pip install fastapi uvicorn


COPY . .

CMD ["uvicorn", "app.main:app",  "--reload", "--host", "0.0.0.0", "--port", "8000", "--env-file", ".env.prod", "--log-level", "debug"]
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--env-file", ".env.dev", "--log-level", "debug"]