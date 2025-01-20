#!/bin/bash

# 현재 실행 중인 App이 green인지 blue인지 확인
IS_GREEN=$(docker ps | grep green)
DEFAULT_CONF="/etc/nginx/nginx.conf"

if [ -z "$IS_GREEN" ]; then
  echo "### BLUE => GREEN ###"

  echo "1. Build and start green container"
  docker-compose up --build -d green # green 컨테이너 빌드 및 실행

  # Health check for green
  while true; do
    echo "2. Green health check..."
    sleep 3
    REQUEST=$(curl -s http://127.0.0.1:8000) # green으로 요청
    if [ -n "$REQUEST" ]; then
      echo "Green health check success"
      break
    fi
  done

  echo "3. Reload Nginx to use green"
  # sudo cp /etc/nginx/nginx.green.conf $DEFAULT_CONF
  sudo rm /etc/nginx/sites-enabled/current
  sudo ln -s /etc/nginx/sites-available/fastapi.conf /etc/nginx/sites-enabled/current
  sudo nginx -s reload

  echo "4. Stop blue container"
  docker-compose stop blue # blue 컨테이너 중지

else
  echo "### GREEN => BLUE ###"

  echo "1. Build and start blue container"
  docker-compose up --build -d blue # blue 컨테이너 빌드 및 실행

  # Health check for blue
  while true; do
    echo "2. Blue health check..."
    sleep 3
    REQUEST=$(curl -s http://127.0.0.1:8002) # blue로 요청
    if [ -n "$REQUEST" ]; then
      echo "Blue health check success"
      break
    fi
  done

  echo "3. Reload Nginx to use blue"
  # sudo cp /etc/nginx/nginx.blue.conf $DEFAULT_CONF
  sudo rm /etc/nginx/sites-enabled/current
  sudo ln -s /etc/nginx/sites-available/blue.conf /etc/nginx/sites-enabled/current
  sudo nginx -s reload

  echo "4. Stop green container"
  docker-compose stop green # green 컨테이너 중지
fi
