"""
S3 공통 설정 모듈
환경 변수에 따라 버킷 이름과 S3 클라이언트를 제공합니다.
"""
import os
import boto3
from botocore.client import Config

# 환경 변수 확인
env = os.getenv("ENV", "dev")

# S3 bucket 이름 설정: dev 환경이면 cafeplatform-dev, 아니면 cafeplatform
BUCKET_NAME = "cafeplatform-dev" if env == "dev" else "cafeplatform"

# S3 클라이언트 설정
S3_CLIENT = boto3.client(
    's3',
    aws_access_key_id='***REMOVED***',
    aws_secret_access_key='***REMOVED***',
    region_name='ap-northeast-2',
    config=Config(signature_version='s3v4', region_name='ap-northeast-2')
)
