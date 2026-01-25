# API 환경별 호출 가이드

## 현재 구조

- **운영 환경**: 포트 8000, 8002 (ENV=production)
- **개발 환경**: 포트 8001 (ENV=development)

## 호출 방법

### 방법 1: URL 경로로 구분 (구현됨)

**개발 환경:**
```
https://www.502company.com/dev/store/search?query=카페
https://www.502company.com/dev/user/123
https://www.502company.com/dev/order/456
```

**운영 환경:**
```
https://www.502company.com/prod/store/search?query=카페
https://www.502company.com/prod/user/123
https://www.502company.com/prod/order/456
```

### 방법 2: 포트로 직접 호출

**개발 환경:**
```
http://www.502company.com:8001/store/search?query=카페
http://www.502company.com:8001/user/123
```

**운영 환경:**
```
http://www.502company.com:8000/store/search?query=카페
http://www.502company.com:8000/user/123
또는
http://www.502company.com:8002/store/search?query=카페
```

## Nginx 설정 (선택사항)

Nginx에서 경로별로 다른 포트로 프록시할 수 있습니다:

```nginx
# 개발 환경
location /dev/ {
    proxy_pass http://127.0.0.1:8001/;
    rewrite ^/dev/(.*)$ /$1 break;
}

# 운영 환경
location /prod/ {
    proxy_pass http://127.0.0.1:8000/;
    rewrite ^/prod/(.*)$ /$1 break;
}
```

## 환경 변수

- `ENV=development` → `/dev/` 경로 사용
- `ENV=production` → `/prod/` 경로 사용
