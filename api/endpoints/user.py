"""
User API 엔드포인트
"""
import traceback
from fastapi import FastAPI, Header, Query, Request, APIRouter, Depends, HTTPException, status
from typing import Optional
import re
from app.auth.auth_dependency import verify_firebase_token
import firebase_admin
from firebase_admin import auth, credentials

def get_user_firebase_app(project_type: str = "user"):
    """사용자 앱 Firebase 앱 반환"""
    if project_type == "dev":
        try:
            return firebase_admin.get_app("dev_app")
        except ValueError:
            pass
    try:
        return firebase_admin.get_app("user_app")
    except ValueError:
        return firebase_admin.get_app()

from typing import Union
from pydantic import BaseModel

import pymysql
import pymysql.err
import app.database as databas
import boto3
from botocore.client import Config
from db.session import get_db_connection, close_db_connection

import logging
import httpx
import os
import time
import json
import jwt

logger = logging.getLogger("cafe_backend")

from models.user import User
from models.user import Inquiry
from models.user import InquiryResponse
from models.user import FindAccountRequest
from models.user import TermsAgreeRequest
from models.push_token import PushTokenCreate, PushTokenUpdate
from models.notice import NoticeResponse
from app.fcm_service import send_fcm_notification_to_user
from core.config import settings
from core.s3_config import S3_CLIENT, TERMS_BUCKET_NAME
from crud import terms as terms_crud

router = APIRouter()


def generate_apple_client_secret():
    """
    Apple Client Secret 생성 (JWT 형식)
    .env 파일에서 여러 줄로 나눠진 Private Key를 합쳐서 사용하여 JWT 토큰 생성
    
    Apple Developer에서 필요한 정보:
    - Team ID
    - Key ID
    - Client ID (Service ID)
    - Private Key (-----BEGIN PRIVATE KEY----- 부터 -----END PRIVATE KEY----- 까지)
    """
    try:
        if not settings.apple_client_id or not settings.apple_team_id or not settings.apple_key_id:
            error_msg = "Apple 설정이 없습니다. Apple revoke를 수행할 수 없습니다."
            logger.error(f"Apple Client Secret 생성 실패: {error_msg}")
            return None
        
        # .env 파일에서 여러 줄로 나눠진 Private Key 합치기
        private_key = settings.get_apple_private_key()
        
        if not private_key or not private_key.strip():
            error_msg = "Apple Private Key가 설정되지 않았습니다. APPLE_PRIVATE_KEY_LINE1~6을 확인하세요."
            logger.error(f"Apple Client Secret 생성 실패: {error_msg}")
            return None
        
        # Private Key 형식 검증 (BEGIN과 END가 있는지 확인)
        if "-----BEGIN PRIVATE KEY-----" not in private_key or "-----END PRIVATE KEY-----" not in private_key:
            error_msg = "Apple Private Key 형식이 올바르지 않습니다. -----BEGIN PRIVATE KEY----- 와 -----END PRIVATE KEY----- 가 포함되어야 합니다."
            logger.error(f"Apple Client Secret 생성 실패: {error_msg}")
            return None
        
        headers = {
            "alg": "ES256",
            "kid": settings.apple_key_id
        }
        
        payload = {
            "iss": settings.apple_team_id,  # Team ID
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,  # 1시간 유효
            "aud": "https://appleid.apple.com",
            "sub": settings.apple_client_id  # Client ID (Service ID)
        }
        
        # ES256 알고리즘으로 JWT 서명 (cryptography 패키지 필요)
        # Private Key는 \n을 포함한 원본 형식 그대로 사용
        client_secret = jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers=headers
        )
        
        return client_secret
    except Exception as e:
        error_msg = f"Apple Client Secret 생성 중 예외 발생: {type(e).__name__}: {str(e)}"
        logger.error(f"Apple Client Secret 생성 실패: {error_msg}")
        traceback.print_exc()
        return None


async def get_apple_refresh_token(authorization_code: str):
    """
    Apple authorization code를 사용하여 refresh_token과 access_token 획득
    
    Args:
        authorization_code: Apple에서 받은 authorization code
    
    Returns:
        dict: {"refresh_token": str, "access_token": str, "id_token": str} 또는 None
    """
    try:
        if not authorization_code:
            error_msg = "Apple authorization_code가 제공되지 않았습니다."
            logger.error(f"Apple token 획득 실패: {error_msg}")
            return None
        
        if not settings.apple_client_id:
            error_msg = f"Apple Client ID가 설정되지 않았습니다. (apple_client_id: {settings.apple_client_id})"
            logger.error(f"Apple token 획득 실패: {error_msg}")
            return None
        
        client_secret = generate_apple_client_secret()
        if not client_secret:
            error_msg = "Apple Client Secret 생성 실패 (Private Key 파일 확인 필요)"
            logger.error(f"Apple token 획득 실패: {error_msg}")
            return None
        
        # Apple token API 엔드포인트
        token_url = "https://appleid.apple.com/auth/token"
        
        # 요청 파라미터 구성 (redirect_uri는 Mobile 앱의 경우 선택적)
        data = {
            "client_id": settings.apple_client_id,
            "client_secret": client_secret,
            "code": authorization_code,
            "grant_type": "authorization_code"
        }
        
        # redirect_uri가 설정되어 있으면 추가 (Web 앱의 경우 필요, Mobile 앱은 선택적)
        if settings.apple_redirect_uri:
            data["redirect_uri"] = settings.apple_redirect_uri
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                refresh_token = token_data.get("refresh_token")
                access_token = token_data.get("access_token")
                
                if refresh_token:
                    logger.info(f"Apple token 획득 성공: refresh_token 있음")
                    return {
                        "refresh_token": refresh_token,
                        "access_token": access_token,
                        "id_token": token_data.get("id_token")
                    }
                elif access_token:
                    # refresh_token이 없지만 access_token이 있는 경우
                    # 이는 이미 로그인한 사용자의 경우일 수 있음
                    # 하지만 revoke를 위해서는 refresh_token이 필요하므로 실패로 처리
                    error_msg = f"Apple token API 응답 성공(200)했지만 refresh_token이 없고 access_token만 있습니다. 이는 이미 로그인한 사용자의 재로그인인 경우일 수 있습니다. 탈퇴를 위해서는 첫 로그인 시 받은 refresh_token이 필요합니다. token_data: {json.dumps({k: v for k, v in token_data.items() if k != 'access_token'}, ensure_ascii=False)}"
                    logger.error(f"Apple token 획득 실패: {error_msg}")
                    print(f"Apple token 획득: refresh_token 없음 (access_token만 있음)")
                    return None
                else:
                    # token_data에 refresh_token도 access_token도 없는 경우
                    error_msg = f"Apple token API 응답 성공(200)했지만 refresh_token과 access_token이 모두 없습니다. token_data: {json.dumps(token_data, ensure_ascii=False)}"
                    logger.error(f"Apple token 획득 실패: {error_msg}")
                    print(f"Apple token 획득: refresh_token과 access_token 모두 없음, token_data: {token_data}")
                    return None
            else:
                error_text = response.text
                try:
                    error_json = response.json()
                    error_detail = json.dumps(error_json, ensure_ascii=False)
                except:
                    error_detail = error_text
                
                error_msg = f"Apple token API 호출 실패 - status_code: {response.status_code}, response: {error_detail}, client_id: {settings.apple_client_id}, authorization_code: {authorization_code[:20]}..."
                logger.error(f"Apple token 획득 실패: {error_msg}")
                print(f"Apple token 획득 실패: {response.status_code} - {error_detail}")
                return None
                
    except httpx.TimeoutException as e:
        error_msg = f"Apple token API 호출 타임아웃: {str(e)}"
        logger.error(f"Apple token 획득 실패: {error_msg}")
        traceback.print_exc()
        return None
    except Exception as e:
        error_msg = f"Apple token 획득 중 예외 발생: {type(e).__name__}: {str(e)}"
        logger.error(f"Apple token 획득 실패: {error_msg}")
        traceback.print_exc()
    return None


async def revoke_apple_token(refresh_token: str):
    """
    Apple 토큰 철회 (revoke) 함수
    refresh_token을 사용하여 Apple revoke API 호출
    
    Args:
        refresh_token: Apple refresh_token (필수)
    
    Returns:
        bool: revoke 성공 여부
    """
    try:
        if not refresh_token:
            error_msg = "Apple refresh_token이 제공되지 않았습니다."
            logger.error(f"Apple revoke 실패: {error_msg}")
            return False
        
        if not settings.apple_client_id:
            error_msg = f"Apple Client ID가 설정되지 않았습니다. (apple_client_id: {settings.apple_client_id})"
            logger.error(f"Apple revoke 실패: {error_msg}")
            return False
        
        client_secret = generate_apple_client_secret()
        if not client_secret:
            error_msg = "Apple Client Secret 생성 실패 (Private Key 파일 확인 필요)"
            logger.error(f"Apple revoke 실패: {error_msg}")
            return False
        
        # Apple revoke API 엔드포인트
        revoke_url = "https://appleid.apple.com/auth/revoke"
        
        # 요청 파라미터 구성 (Apple revoke API는 refresh_token이 필수)
        data = {
            "client_id": settings.apple_client_id,
            "client_secret": client_secret,
            "token": refresh_token,
            "token_type_hint": "refresh_token"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                revoke_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code == 200:
                logger.info("Apple 토큰 revoke 성공")
                return True
            else:
                error_text = response.text
                error_msg = f"Apple revoke API 호출 실패 - status_code: {response.status_code}, response: {error_text}, client_id: {settings.apple_client_id}, refresh_token: {refresh_token[:20]}..."
                logger.error(f"Apple revoke 실패: {error_msg}")
                print(f"Apple revoke 실패: {response.status_code} - {error_text}")
                return False
                
    except httpx.TimeoutException as e:
        error_msg = f"Apple revoke API 호출 타임아웃: {type(e).__name__}: {str(e)}, refresh_token: {refresh_token[:20]}..."
        logger.error(f"Apple revoke 실패: {error_msg}")
        traceback.print_exc()
        return False
    except Exception as e:
        error_msg = f"Apple revoke 중 예외 발생: {type(e).__name__}: {str(e)}, refresh_token: {refresh_token[:20]}..."
        logger.error(f"Apple revoke 실패: {error_msg}")
        traceback.print_exc()
        return False

@router.post("/register")
def signUp(user: User, firebase_project: Optional[str] = None):
    """
    회원가입/링크 로직:
    - provider가 email이면 user 테이블의 fb_email 컬럼에 request의 email 저장
    - 그 외면 user 테이블의 email 컬럼에 request의 email 저장
    - user 테이블에 존재하는 phone이 있으면 user_provider 추가, 없으면 신규가입
    """
    project_type = firebase_project.lower() if firebase_project else "user"

    uid = user.uid
    email = user.email  # request에서 받은 email
    provider = user.provider  # request에서 받은 provider
    phone_number = user.phone_number  # request에서 받은 phone
    
    if not email or not provider or not phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email, provider, and phone_number are required"
        )

    user_app = get_user_firebase_app(project_type)
    user_record = auth.get_user(uid, app=user_app)
    # 요청으로 받은 name을 사용, 없으면 Firebase의 display_name 사용
    name = user.name or user_record.display_name
    
    print("signUp request:", uid, email, name, phone_number, provider)
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. user 테이블에서 phone으로 기존 사용자 확인
        cursor.execute("SELECT * FROM user WHERE phone = %s LIMIT 1", (phone_number,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            # 기존 사용자가 있는 경우 (등록된 경우) - user_provider 추가
            user_id = existing_user["id"]
            existing_email = existing_user.get("email") or ""
            existing_fb_email = existing_user.get("fb_email") or ""
            existing_uid = existing_user.get("uid") or ""

            print(f"기존 사용자 발견: user_id={user_id}, email={existing_email}, uid={existing_uid}")

            # user_provider 추가 로직
            update_fields = []
            update_values = []

            # provider가 email이면 fb_email, 그 외면 email 컬럼에 값 추가
            if provider == "email":
                if not existing_fb_email and email:
                    update_fields.append("fb_email = %s")
                    update_values.append(email)
                    print(f"user 테이블 fb_email 업데이트: {email}")
            else:
                if not existing_email and email:
                    update_fields.append("email = %s")
                    update_values.append(email)
                    print(f"user 테이블 email 업데이트: {email}")
            
            # uid가 없으면 업데이트
            if not existing_uid:
                update_fields.append("uid = %s")
                update_values.append(uid)
                print(f"user 테이블 uid 업데이트: {uid}")
            
            # user 테이블 업데이트
            if update_fields:
                update_values.append(user_id)
                update_query = f"UPDATE user SET {', '.join(update_fields)} WHERE id = %s"
                cursor.execute(update_query, tuple(update_values))
                connection.commit()
            
            # user_provider 추가
            linkAccount(uid, user_id, provider, email, project_type)

            return {"user_id": user_id, "message": "user_provider added to existing user"}
        else:
            # 신규 가입
            print("신규 가입 진행")

            # 약관 동의가 있으면 검증 (필수 약관 미동의 시 가입 전에 400)
            if user.agreements is not None and len(user.agreements) > 0:
                agreements_list = [{"term_id": a.term_id, "term_version_id": a.term_version_id, "agreed": a.agreed} for a in user.agreements]
                valid, err_msg = terms_crud.validate_user_agreements(connection, agreements_list)
                if not valid:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)

            # provider가 email이면 fb_email에, 그 외면 email에 저장
            email_val = (email or "") if provider != "email" else ""
            fb_email_val = (email or "") if provider == "email" else ""
            insert_query = """
                INSERT INTO user (
                    name, email, phone, uid, fb_email
                ) VALUES (%s, %s, %s, %s, %s);
            """
            cursor.execute(insert_query, (name, email_val, phone_number, uid, fb_email_val))
            print(f"신규 사용자 생성: email={email}, provider={provider}")

        connection.commit()
        user_id = cursor.lastrowid
        print(f"신규 사용자 생성 완료: user_id={user_id}, provider={provider}")
        
        # user_provider 추가
        linkAccount(uid, user_id, provider, email, project_type)

        # 신규 가입 시 약관 동의 정보 저장
        if not existing_user and user.agreements is not None and len(user.agreements) > 0:
            agreements_list = [{"term_id": a.term_id, "term_version_id": a.term_version_id, "agreed": a.agreed} for a in user.agreements]
            success, err_msg, _ = terms_crud.save_user_agreements(connection, user_id, agreements_list)
            if not success:
                # 이미 유저는 생성됨; 로그만 남기고 응답은 성공 (동의는 나중에 /terms/agree로 보완 가능)
                logger.warning(f"signUp 약관 저장 실패 user_id={user_id}: {err_msg}")
        
        return {"user_id": user_id, "message": "new user registered"}
                                                  
    except Exception as e:
        print(f"signUp 오류: {e}")
        traceback.print_exc()
        connection.rollback()
        logger.error(f"signUp 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"signUp failed: {str(e)}"
        )
    finally:
        close_db_connection(connection)
        
def linkAccount(uid, user_id, provider, email, project_type: str = "user"):
    print("linkAccount")
    user_app = get_user_firebase_app(project_type)
    user_record = auth.get_user(uid, app=user_app)
    print("user_record\n\n")
    
    # email = user_record.email
    phone_number = user_record.phone_number 
    # provider = user.get("firebase").get("sign_in_provider")  
    
    # provider가 None인 경우 기본값 설정
    if provider is None:
        provider = "unknown"
    
    print("user", uid, email, phone_number, provider)
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor()
    
    try:
        print(user_id)
        
        # 중복 체크: 이미 같은 user_id, email, provider 조합이 존재하는지 확인
        # Apple private relay 이메일의 경우 apple.com과 apple.priavate를 동일한 것으로 취급
        check_query = """
            SELECT * FROM user_provider 
            WHERE user_id = %s AND email = %s AND provider = %s
            FOR UPDATE;
        """
        cursor.execute(check_query, (user_id, email, provider))
        existing = cursor.fetchone()
        
        # Apple private relay 이메일의 경우 apple.com과 apple.priavate를 동일한 것으로 취급
        if not existing and email.endswith("@privaterelay.appleid.com"):
            if provider == "apple.priavate":
                # apple.priavate로 저장하려는데 apple.com이 이미 있는지 확인
                cursor.execute(check_query, (user_id, email, "apple.com"))
                existing = cursor.fetchone()
            elif provider == "apple.com":
                # apple.com으로 저장하려는데 apple.priavate가 이미 있는지 확인
                cursor.execute(check_query, (user_id, email, "apple.priavate"))
        existing = cursor.fetchone()
        
        if existing:
            print(f"이미 등록된 user_provider: user_id={user_id}, email={email}, provider={provider}")
            connection.rollback()
            return
        
        # INSERT IGNORE를 사용하여 중복 시 무시 (추가 안전장치)
        query = """
            INSERT IGNORE INTO user_provider (
                user_id, email, provider
            ) VALUES (%s, %s, %s);
        """

        cursor.execute(query, (user_id, email, provider))
        
        # 영향받은 행이 0이면 이미 존재 (INSERT IGNORE가 작동한 경우)
        if cursor.rowcount == 0:
            print(f"이미 존재하는 user_provider (INSERT IGNORE): user_id={user_id}, email={email}, provider={provider}")
            connection.rollback()
            return
        
        connection.commit()
                                                  
    except pymysql.err.IntegrityError as e:
        # 고유 제약 조건 위반 시 (중복 키 에러)
        error_code, error_msg = e.args
        print(f"중복된 user_provider (IntegrityError): user_id={user_id}, email={email}, provider={provider}, error={error_msg}")
        connection.rollback()
        return  # 중복이므로 정상 종료
    except Exception as e:
        print(e)
        connection.rollback()
        raise
    finally:
        close_db_connection(connection)

@router.get("/login/{email}")
async def login_user(
    email: str,
    provider: str = Query(..., description="로그인 provider (예: email, oidc.kakao, oidc.apple 등)"),
    firebase_project: Optional[str] = Header(None, alias="X-Firebase-Project"),
    user=Depends(verify_firebase_token)
):
    """
    Firebase 토큰 기반 로그인.
    클라이언트는 email과 provider를 전달해야 합니다.
    서버가 Firebase 토큰에서 uid를 읽어 DB 조회에 활용합니다.
    provider는 DB 쿼리에 직접 사용됩니다.
    """
    project_type = firebase_project.lower() if firebase_project else "user"

    print(user)
    
    # user가 None인 경우 처리 (웹 요청 등)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    uid = user.get("uid")
    
    # provider 유효성 검사
    if not provider or provider.strip() == "":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider is required"
        )
    
    provider = provider.strip()
    
    try:
        user_app = get_user_firebase_app(project_type)
        user_record = auth.get_user(uid, app=user_app)
        email2 = user_record.email
    except Exception as e:
        # Firebase에 사용자가 없거나 다른 에러 발생
        error_msg = f"Firebase user not found or error: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_msg
        )

    print("login_user firebase 인증 성공", email, email2, uid, provider)
    
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    # Apple private relay 이메일 처리 (provider 변환은 조회 전에만 수행)
    original_provider = provider
    if email.endswith("@privaterelay.appleid.com"):
        provider = "apple.priavate"

    try:
        # provider를 활용한 DB 쿼리 (N+1 쿼리 문제 해결)
        # 변환된 provider로 user_provider 테이블 조회
        cursor.execute("""
            SELECT u.*,
                   CASE WHEN up.id IS NOT NULL THEN 1 ELSE 0 END as islinked
            FROM user u
            LEFT JOIN user_provider up ON u.id = up.user_id
                AND up.email = %s
                AND up.provider = %s
            WHERE u.uid = %s
            LIMIT 1;
        """, (email, provider, uid))

        result = cursor.fetchone()

        if email == "apple":
             islinked = True
        elif result:
            islinked = result.get("islinked", 0) == 1
        else:
            islinked = None

        if result:
            user_id = result["id"]
            user_email = result.get("email") or None

            print("이미 등록 islinked", islinked)
            # 이미 등록된 유저

            if not islinked:
                print("islinked false")
                linkAccount(uid, user_id, provider, email, project_type)
            else:
                print("islinked true")

            cursor.execute("UPDATE user SET last_login = NOW() WHERE id = %s", (user_id,))
            connection.commit()

            return {
                "isRegistered": 1,
                "user_id": result["id"],
                "name": result["name"],
                "email": user_email,
                "phone_number": result["phone"],
            }
        else:
            print("미등록")

            # 아직 등록되지 않은 유저
            # Firebase에서 phone_number 가져오기
            phone_number = user_record.phone_number if hasattr(user_record, 'phone_number') and user_record.phone_number else None
            
            # 받은 provider를 사용하여 User 객체 생성
            signup_user = User(
                uid=uid,
                provider=provider,
                email=email,
                phone_number=phone_number  # Firebase에서 가져온 phone_number 사용
            )
            signUp(signup_user, project_type)

            return {
                "isRegistered": 0,
                # "uid": uid,       # 고객 uid 제공
                "email": email,
            }

    except Exception as e:
        print("login 오류", e)
        logger.error(f"서버 오류 발생: {str(e)}")
        connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"login failed: {str(e)}"
        )

    finally:
        close_db_connection(connection)


@router.get("/isRegistered")
async def idRegisteredUser(
    provider: str = Query(...),
    email: str = Query(None, description="SNS 가입 유저 확인용 (email, provider로 조회)"),
    phone: str = Query(None, description="Email 가입 유저 확인용 (phone, provider로 조회)"),
    firebase = Depends(verify_firebase_token)
):
    """
    등록 여부 검사
    - provider는 필수
    - email이 제공되면: email + provider로 조회 (SNS 가입 유저 확인)
    - phone이 제공되면: phone + provider로 조회 (email 가입 유저 확인)
    - email과 phone 모두 제공되면 둘 다 확인 (OR 조건)
    - phone만 제공되어도 조회 가능
    """
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        # email과 phone이 모두 없는 경우 에러
        if not email and not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email or phone is required"
            )
        
        # Apple private relay 이메일 처리
        if email and email.endswith("@privaterelay.appleid.com"):
            provider = "apple.priavate"
        
        result = None
        
        # SNS 가입 유저 확인: email + provider로 조회
        if email:
            cursor.execute("""
                SELECT up.* 
                FROM user_provider up
                WHERE up.email = %s AND up.provider = %s
                LIMIT 1;
            """, (email, provider))
            result = cursor.fetchone()
            if result:
                print(f"SNS 가입 유저 확인됨: email={email}, provider={provider}")
                return {'isRegistered': True}
        
        # Email 가입 유저 확인: phone + provider로 조회
        # phone만 있어도 조회 가능
        if phone:
            cursor.execute("""
                SELECT up.* 
                FROM user_provider up
                INNER JOIN user u ON up.user_id = u.id
                WHERE u.phone = %s AND up.provider = %s
                LIMIT 1;
            """, (phone, provider))
            result = cursor.fetchone()
            if result:
                print(f"Email 가입 유저 확인됨: phone={phone}, provider={provider}, user_id={result.get('user_id')}, up_id={result.get('id')}")
                logger.info(f"Email 가입 유저 확인됨: phone={phone}, provider={provider}, user_id={result.get('user_id')}, up_id={result.get('id')}")
                return {'isRegistered': True}
            # 디버깅: phone으로 user는 있는데 해당 provider가 없는 경우
            cursor.execute("SELECT id, phone FROM user WHERE phone = %s LIMIT 1", (phone,))
            user_check = cursor.fetchone()
            if user_check:
                cursor.execute("SELECT provider FROM user_provider WHERE user_id = %s", (user_check['id'],))
                existing_providers = cursor.fetchall()
                provider_list = [p['provider'] for p in existing_providers] if existing_providers else []
                print(f"Email 가입 유저 확인 실패: phone={phone}, provider={provider}, user_id={user_check['id']}, 기존 providers={provider_list}")
                logger.info(f"Email 가입 유저 확인 실패: phone={phone}, provider={provider}, user_id={user_check['id']}, 기존 providers={provider_list}")

        # 결과 확인 (일치하는 값이 없으면 등록 안됨)
        return {'isRegistered': False}

    except HTTPException:
        raise
    except Exception as e:
        print("isRegistered 오류", e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed check registration: {str(e)}"
        )
    finally:
        close_db_connection(connection)
        
@router.get("/isRegistered/phone")
async def idRegisteredUserByPhone(
    phoneNumber: str = Query(...),
    firebase = Depends(verify_firebase_token)
):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
    cursor = connection.cursor()

    try:
        cursor.execute('''SELECT * FROM user WHERE phone=%s;''', (phoneNumber,))

        # 결과 확인 (1개 이상의 행이 반환되면 폰번호가 존재)
        if cursor.fetchone():
            return {'isRegistered': True}
        else:
            return {'isRegistered': False}

    except Exception as e:
        print("isRegistered 오류", e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed check registration: {str(e)}"
        )
    finally:
        cursor.close()

@router.get("/isRegistered/{phoneNumber}")
async def idRegisteredAppleUser(phoneNumber: str):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
    cursor = connection.cursor()

    try:
        cursor.execute('''SELECT * FROM user WHERE phone=%s;''', (phoneNumber,))

        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if cursor.fetchone():
            return {'isRegistered': True}
        else:
            return {'isRegistered': False}

    except Exception as e:
        print("isRegistered 오류", e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed check registration: {str(e)}"
        )
    finally:
        close_db_connection(connection)

@router.post("/inquiry/{user_id}")
async def subjectInquiry(user_id: int, inquiry: Inquiry):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO inquiry (
                user_id, title, content
            ) VALUES (
              {}, '{}', '{}'
            );
        """.format(
            user_id,
            inquiry.title,
            inquiry.content,
            )
            
        cursor.execute(query)
        connection.commit()
                
        return {"message": "inquiry registered successfully"}
    except Exception as e:
        print(e)
        traceback.print_exc() 
        logger.error(f"Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed register inquiry: {str(e)}"
        )

    finally:
        close_db_connection(connection)

#유저용. 
@router.get("/inquiry/{user_id}")
async def getInquiry(user_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                 
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM inquiry WHERE user_id=%s ;''', (user_id,))
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM inquiry_response WHERE inquiry_id=%s ;''', (inquiry['id'],))
            response = cursor.fetchone() 
            
            result = {
                "title": inquiry['title'],
                "content": inquiry['content'],
                "status": inquiry['status'],
                "inquiry_created": inquiry['created_at'],
                "response": response['response'] if response else None,
                "response_created": response['created_at'] if response else None,
            }
            
            inquiry_list.append(result)
                
        return {'inquiry_list': list(reversed(inquiry_list))}
    except Exception as e:
        print(e)
        traceback.print_exc() 
        logger.error(f"Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed get inquiry: {str(e)}"
        )

    finally:
        close_db_connection(connection)

#모든 문의내역 불러오기
@router.get("/inquiry")
async def getInquiry():
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM inquiry;''')
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM inquiry_response WHERE inquiry_id=%s;''', (inquiry['id'],))
            response = cursor.fetchone() 
            
            result = {
                "id": inquiry['id'],
                "title": inquiry['title'],
                "content": inquiry['content'],
                "status": inquiry['status'],
                "inquiry_created": inquiry['created_at'],
                "response": response['response'] if response else None,
                "response_created": response['created_at'] if response else None,
            }
            
            inquiry_list.append(result)
            print(inquiry_list)
                
        return {'inquiry_list': list(reversed(inquiry_list))}
    except Exception as e:
        print(e)
        traceback.print_exc() 
        logger.error(f"Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed get all inquiry: {str(e)}"
        )

    finally:
        close_db_connection(connection)


# ---------- 약관 동의 ----------

_USER_TERM_TYPE_TO_PREFIX = {
    "SERVICE": "service_term",
    "PRIVACY": "privacy_term",
    "PRIVACY_CONSENT": "privacy_consent_term",
    "MARKETING": "marketing_term",
    "LOCATION": "location_term",
}
_USER_TERM_TYPE_TO_CATEGORY = {
    "SERVICE": "service",
    "PRIVACY": "privacy",
    "PRIVACY_CONSENT": "privacy_consent",
    "MARKETING": "marketing",
    "LOCATION": "location",
}
VALID_USER_TERM_TYPES = set(_USER_TERM_TYPE_TO_PREFIX.keys())


@router.get("/terms/content")
def get_user_term_content(
    term_type: str = Query(..., description="SERVICE | PRIVACY | MARKETING | LOCATION"),
):
    """유저 약관 본문 조회. DB에서 현재 시행 중인 최신 버전 확인 후 S3에서 HTML 반환."""
    term_type = term_type.upper()
    if term_type not in VALID_USER_TERM_TYPES:
        raise HTTPException(status_code=400, detail=f"term_type must be one of {sorted(VALID_USER_TERM_TYPES)}")

    connection = get_db_connection()
    try:
        info = terms_crud.get_user_term_content_info(connection, term_type)
        if not info:
            raise HTTPException(status_code=404, detail="현재 시행 중인 약관 버전이 없습니다.")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"get_user_term_content DB error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        close_db_connection(connection)

    version = info["version"]
    prefix = _USER_TERM_TYPE_TO_PREFIX[term_type]
    filename = f"{prefix}_{version}.html"
    category = _USER_TERM_TYPE_TO_CATEGORY[term_type]
    key = f"terms/user/{category}/{filename}"

    try:
        obj = S3_CLIENT.get_object(Bucket=TERMS_BUCKET_NAME, Key=key)
        content = obj["Body"].read().decode("utf-8", errors="replace")
        return {"content": content, "term_type": term_type, "version": version}
    except Exception as e:
        err_str = str(e)
        err_lower = err_str.lower()
        logger.error(f"get_user_term_content S3 error: bucket={TERMS_BUCKET_NAME}, key={key}, error={err_str}")
        if "nosuchkey" in err_lower or "404" in err_lower or "no such key" in err_lower:
            raise HTTPException(status_code=404, detail=f"약관 파일을 찾을 수 없습니다. key: {key}")
        if "accessdenied" in err_lower or "forbidden" in err_lower:
            raise HTTPException(status_code=403, detail="S3 access denied")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=err_str)


@router.get("/terms/presigned-url")
def get_user_term_presigned_url(
    term_type: str = Query(..., description="SERVICE | PRIVACY | PRIVACY_CONSENT | MARKETING | LOCATION"),
):
    """유저 약관 HTML 파일의 S3 presigned GET URL 반환."""
    term_type = term_type.upper()
    if term_type not in VALID_USER_TERM_TYPES:
        raise HTTPException(status_code=400, detail=f"term_type must be one of {sorted(VALID_USER_TERM_TYPES)}")

    connection = get_db_connection()
    try:
        info = terms_crud.get_user_term_content_info(connection, term_type)
        if not info:
            raise HTTPException(status_code=404, detail="현재 시행 중인 약관 버전이 없습니다.")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"get_user_term_presigned_url DB error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        close_db_connection(connection)

    version = info["version"]
    prefix = _USER_TERM_TYPE_TO_PREFIX[term_type]
    filename = f"{prefix}_{version}.html"
    category = _USER_TERM_TYPE_TO_CATEGORY[term_type]
    key = f"terms/user/{category}/{filename}"

    try:
        url = S3_CLIENT.generate_presigned_url(
            'get_object',
            Params={"Bucket": TERMS_BUCKET_NAME, "Key": key},
            ExpiresIn=3600,
        )
        return {"url": url, "term_type": term_type, "version": version}
    except Exception as e:
        err_str = str(e)
        logger.error(f"get_user_term_presigned_url S3 error: bucket={TERMS_BUCKET_NAME}, key={key}, error={err_str}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=err_str)


@router.get("/terms/current")
def get_terms_current():
    """현재 시행 중인 약관 목록 (회원가입/재동의 화면 노출용)."""
    connection = get_db_connection()
    try:
        terms = terms_crud.get_current_terms(connection, "user")
        return {"terms": terms}
    except Exception as e:
        traceback.print_exc()
        logger.error(f"get_terms_current: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        close_db_connection(connection)


@router.get("/{user_id}/terms/status")
def get_user_terms_status(user_id: int):
    """유저의 약관별 동의 상태 및 재동의 필요 여부. 공지만 약관은 시행일 지나면 자동 저장."""
    connection = get_db_connection()
    try:
        result = terms_crud.get_user_terms_status(connection, user_id)
        return result
    except Exception as e:
        traceback.print_exc()
        logger.error(f"get_user_terms_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        close_db_connection(connection)


@router.post("/terms/agree")
def post_terms_agree(body: TermsAgreeRequest):
    """약관 동의 저장 (회원가입/재동의 시). 필수 약관은 반드시 agreed=True."""
    connection = get_db_connection()
    try:
        agreements = [{"term_id": a.term_id, "term_version_id": a.term_version_id, "agreed": a.agreed} for a in body.agreements]
        success, err_msg, agreed_count = terms_crud.save_user_agreements(connection, body.user_id, agreements)
        if not success:
            raise HTTPException(status_code=400, detail=err_msg)
        return {"success": True, "message": "약관 동의가 저장되었습니다.", "agreed_count": agreed_count}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.error(f"post_terms_agree: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        close_db_connection(connection)


@router.post("/reply/{inquiry_id}")
async def subjectReply(inquiry_id: int, reply: InquiryResponse):
    connection = get_db_connection()  # 환경에 맞는 DB 연결               
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. inquiry 정보 조회 (user_id, title 가져오기)
        cursor.execute('''
            SELECT user_id, title 
            FROM inquiry 
            WHERE id = %s
        ''', (inquiry_id,))
        inquiry = cursor.fetchone()
        
        if not inquiry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inquiry with id {inquiry_id} not found"
            )
        
        user_id = inquiry['user_id']
        inquiry_title = inquiry['title']
        
        # 2. 기존 답변 확인
        cursor.execute('SELECT id FROM inquiry_response WHERE inquiry_id = %s', (inquiry_id,))
        existing_response = cursor.fetchone()
        
        if existing_response:
            # 기존 답변이 있으면 UPDATE
            cursor.execute('''
                UPDATE inquiry_response 
                SET response = %s, updated_at = NOW()
                WHERE inquiry_id = %s
            ''', (reply.response, inquiry_id))
        else:
            # 기존 답변이 없으면 INSERT
            cursor.execute('''
                INSERT INTO inquiry_response (inquiry_id, response)
                VALUES (%s, %s)
            ''', (inquiry_id, reply.response))
        
        # 3. inquiry 테이블의 status를 'answered'로 변경
        query_update_status = """
            UPDATE inquiry
            SET status = 'answered'
            WHERE id = %s;
        """
        cursor.execute(query_update_status, (inquiry_id,))
        
        # 변경 사항을 커밋
        connection.commit()
        
        # 4. FCM 푸시 메시지 전송
        try:
            send_fcm_notification_to_user(
                user_id=user_id,
                title="문의 답변이 등록되었습니다",
                body=f"[{inquiry_title}] 문의에 대한 답변이 등록되었습니다."
            )
        except Exception as fcm_error:
            logger.error(f"Failed to send FCM notification: {str(fcm_error)}")
            # FCM 전송 실패해도 답변은 성공한 것으로 처리
        
        return {"message": "reply registered successfully"}
    except Exception as e:
        print(e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed register reply: {str(e)}"
        )
    finally:
        close_db_connection(connection)

def parse_user_agent(user_agent: Optional[str]) -> dict:
    """
    User-Agent 파싱: '$appName/$appVersion ($platform; $osVersion; $deviceModel)'
    예: 'MyApp/1.0.0 (iOS; 17.0; iPhone14,2)'
    """
    result = {
        'app_name': None,
        'app_version': None,
        'platform': None,
        'os_version': None,
        'device_model': None
    }
    
    if not user_agent:
        return result
    
    # 패턴: appName/appVersion (platform; osVersion; deviceModel)
    pattern = r'([^/]+)/([^\s]+)\s+\(([^;]+);\s*([^;]+);\s*([^)]+)\)'
    match = re.match(pattern, user_agent)
    
    if match:
        result['app_name'] = match.group(1).strip()
        result['app_version'] = match.group(2).strip()
        result['platform'] = match.group(3).strip()
        result['os_version'] = match.group(4).strip()
        result['device_model'] = match.group(5).strip()
    
    return result

@router.post("/push-token/{user_id}")
async def registerPushToken(
    user_id: int,
    push_token: PushTokenCreate,
    user_agent: Optional[str] = Header(None, alias="User-Agent")
):
    """
    처음 가입 시 push token 정보를 저장하는 API
    모든 컬럼값 정보를 받아서 저장
    User-Agent 헤더에서 app_version, os_version 파싱
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # User-Agent 파싱
        ua_info = parse_user_agent(user_agent)
        app_version = ua_info.get('app_version')
        os_version = ua_info.get('os_version')
        
        # device_type 기준으로 기존 행 확인 (토큰이 바뀌어도 같은 디바이스면 UPDATE)
        cursor.execute('''
            SELECT id FROM user_push_tokens
            WHERE user_id = %s AND device_type = %s
        ''', (user_id, push_token.device_type.value))
        existing = cursor.fetchone()

        if existing:
            cursor.execute('''
                UPDATE user_push_tokens
                SET fcm_token = %s,
                    allow_service_push = %s,
                    allow_marketing_push = %s,
                    app_version = %s,
                    os_version = %s
                WHERE id = %s
            ''', (
                push_token.fcm_token,
                1 if push_token.allow_service_push else 0,
                1 if push_token.allow_marketing_push else 0,
                app_version,
                os_version,
                existing['id']
            ))
        else:
            # 새로 저장
            cursor.execute('''
                INSERT INTO user_push_tokens (
                    user_id, fcm_token, device_type,
                    allow_service_push, allow_marketing_push,
                    app_version, os_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                user_id,
                push_token.fcm_token,
                push_token.device_type.value,
                1 if push_token.allow_service_push else 0,
                1 if push_token.allow_marketing_push else 0,
                app_version,
                os_version
            ))
        
        connection.commit()
        
        return {
            "message": "Push token registered successfully",
            "user_id": user_id
        }
        
    except Exception as e:
        print(f"Error during registerPushToken: {e}")
        traceback.print_exc()
        logger.error(f"Error during registerPushToken: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during registerPushToken: {str(e)}"
        )
    finally:
        cursor.close()
        close_db_connection(connection)

@router.delete("/push-token/{user_id}")
async def deletePushToken(
    user_id: int,
    fcm_token: str = Header(None, alias="X-FCM-Token")
):
    if not fcm_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="FCM token is required in header"
        )

    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''
            DELETE FROM user_push_tokens
            WHERE user_id = %s AND fcm_token = %s
        ''', (user_id, fcm_token))
        connection.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Push token not found"
            )

        return {"message": "Push token deleted successfully", "user_id": user_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during deletePushToken: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during deletePushToken: {str(e)}"
        )
    finally:
        cursor.close()
        close_db_connection(connection)


@router.patch("/push-token/{user_id}")
async def updatePushTokenAgreement(
    user_id: int,
    push_token_update: PushTokenUpdate,
    fcm_token: str = Header(None, alias="X-FCM-Token")
):
    """
    동의 여부 변경 시 사용하는 API
    allow_service_push, allow_marketing_push만 변경
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        if not fcm_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="FCM token is required in header"
            )
        
        # 업데이트할 필드 구성
        update_fields = []
        update_values = []
        
        if push_token_update.allow_service_push is not None:
            update_fields.append("allow_service_push = %s")
            update_values.append(1 if push_token_update.allow_service_push else 0)
            
            # 서비스 푸시를 꺼면 마케팅 푸시도 같이 꺼짐
            if not push_token_update.allow_service_push:
                update_fields.append("allow_marketing_push = %s")
                update_values.append(0)
        
        if push_token_update.allow_marketing_push is not None:
            update_fields.append("allow_marketing_push = %s")
            update_values.append(1 if push_token_update.allow_marketing_push else 0)
        
        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one agreement field must be provided"
            )
        
        update_values.extend([user_id, fcm_token])
        
        query = f'''
            UPDATE user_push_tokens 
            SET {', '.join(update_fields)}
            WHERE user_id = %s AND fcm_token = %s
        '''
        
        cursor.execute(query, update_values)
        connection.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Push token not found"
            )
        
        return {
            "message": "Push token agreement updated successfully",
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during updatePushTokenAgreement: {e}")
        traceback.print_exc()
        logger.error(f"Error during updatePushTokenAgreement: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during updatePushTokenAgreement: {str(e)}"
        )
    finally:
        cursor.close()
        close_db_connection(connection)

@router.delete("/{user_id}")
async def deleteUser(
    user_id: int, 
    authorization_code: Optional[str] = Query(None, description="Apple authorization_code (Apple 유저인 경우 탈퇴 직전에 발급받은 code 필수)"),
    user=Depends(verify_firebase_token)
):
    """
    회원 탈퇴 API (Soft Delete)
    user_id에 해당하는 사용자 정보를 soft delete 처리
    - Apple 유저인 경우 authorization_code를 받아서 서버에서 refresh_token을 획득한 후 Apple revoke API 호출
    - user_provider 테이블에서 user_id 삭제
    - user 테이블에서 email, phone, name 삭제 (빈 값으로 설정)
    - user 테이블에서 is_deleted = 1 설정
    
    참고: Firebase 탈퇴는 서버에서 별도로 처리합니다.
    
    Query Parameters:
    - authorization_code: Apple 유저인 경우 탈퇴 직전에 발급받은 authorization_code를 전달해야 합니다.
                         서버에서 이 code로 refresh_token을 획득하고 revoke를 수행합니다.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. 사용자 존재 여부 확인 (이미 삭제된 것은 제외)
        cursor.execute('SELECT id, uid FROM user WHERE id = %s AND (is_deleted IS NULL OR is_deleted = 0)', (user_id,))
        user_record = cursor.fetchone()
        
        if not user_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {user_id} not found or already deleted"
            )
        
        user_uid = user_record.get("uid")
        
        # 2. Apple 유저 확인 및 revoke 처리
        cursor.execute('''
            SELECT provider, email
            FROM user_provider 
            WHERE user_id = %s AND (
                provider LIKE '%%apple%%' OR 
                provider = 'oidc.apple' OR
                provider = 'apple' OR
                provider = 'apple.priavate'
            )
        ''', (user_id,))
        apple_providers = cursor.fetchall()
        
        apple_revoked = False
        revoke_error_message = None
        
        if apple_providers:
            if not authorization_code:
                error_msg = f"Apple user {user_id}인데 authorization_code가 제공되지 않았습니다. Apple revoke를 건너뜁니다."
                logger.error(f"Apple revoke 실패: {error_msg}")
                revoke_error_message = error_msg
                print(f"Apple user {user_id}: authorization_code 없음, Apple revoke 건너뜀")
            else:
                try:
                    logger.info(f"Apple user {user_id} revoke 시도: authorization_code로 refresh_token 획득 시도")
                    print(f"Apple user {user_id} revoke 시도: authorization_code 사용")
                    
                    # authorization_code로 refresh_token 획득
                    token_data = await get_apple_refresh_token(authorization_code)
                    
                    if token_data and token_data.get("refresh_token"):
                        apple_refresh_token = token_data.get("refresh_token")
                        logger.info(f"Apple user {user_id}: refresh_token 획득 성공")
                        print(f"Apple refresh_token 획득 성공")
                        
                        # Apple revoke API 호출
                        logger.info(f"Apple user {user_id}: refresh_token으로 revoke API 호출")
                        print(f"Apple revoke API 호출 시작")
                        
                        apple_revoked = await revoke_apple_token(apple_refresh_token)
                        
                        if apple_revoked:
                            logger.info(f"Apple user {user_id} (uid: {user_uid}) revoked successfully")
                            print(f"Apple user {user_id} revoked successfully")
                        else:
                            error_msg = f"Apple user {user_id} revoke API 호출 실패. refresh_token은 획득했지만 revoke API 호출이 실패했습니다. (상세 내용은 위 로그 참조)"
                            logger.error(f"Apple revoke 실패: {error_msg}")
                            revoke_error_message = error_msg
                            print(f"Apple revoke 실패 (탈퇴는 계속 진행)")
                    else:
                        # authorization_code로 refresh_token 획득 실패
                        # 이는 authorization_code가 이미 사용되었거나, 만료되었거나, 유효하지 않거나, 이미 로그인한 사용자의 재로그인인 경우일 수 있음
                        error_msg = f"Apple user {user_id}의 refresh_token 획득 실패. authorization_code로 token API를 호출했지만 refresh_token을 얻지 못했습니다. 가능한 원인: 1) authorization_code가 이미 사용됨, 2) authorization_code 만료, 3) authorization_code가 유효하지 않음, 4) 이미 로그인한 사용자의 재로그인(이 경우 refresh_token 없이 access_token만 제공됨). 탈퇴를 위해서는 첫 로그인 시 받은 refresh_token이 필요합니다. (상세 내용은 위 로그 참조)"
                        logger.error(f"Apple revoke 실패: {error_msg}")
                        revoke_error_message = error_msg
                        print(f"Apple refresh_token 획득 실패 (탈퇴는 계속 진행)")
                    
                except Exception as e:
                    error_msg = f"Apple user {user_id} revoke 처리 중 예외 발생: {type(e).__name__}: {str(e)}"
                    logger.error(f"Apple revoke 실패: {error_msg}")
                    revoke_error_message = error_msg
                    traceback.print_exc()
                    print(f"Apple revoke 오류 (탈퇴는 계속 진행): {str(e)}")
        
        # 3. 관련 데이터 삭제
        # user_provider 테이블에서 user_id 삭제
        cursor.execute('DELETE FROM user_provider WHERE user_id = %s', (user_id,))
        
        # push tokens 삭제
        cursor.execute('DELETE FROM user_push_tokens WHERE user_id = %s', (user_id,))
        
        # 4. user 테이블 업데이트: 개인정보 삭제, is_deleted = 1, deleted_at = 현재시간 설정
        cursor.execute('''
            UPDATE user 
            SET email = '', 
                phone = '', 
                name = '', 
                fb_email = '',
                uid = '',
                is_deleted = 1,
                deleted_at = NOW()
            WHERE id = %s
        ''', (user_id,))
        
        connection.commit()
        
        logger.info(f"User {user_id} soft deleted successfully")
        
        response_data = {
            "message": "User deleted successfully",
            "user_id": user_id,
            "apple_revoked": apple_revoked
        }
        
        # Apple revoke 실패 시 에러 메시지 추가 (AWS CloudWatch에도 상세 로깅됨)
        if apple_providers and not apple_revoked and revoke_error_message:
            response_data["apple_revoke_error"] = revoke_error_message
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during deleteUser: {e}")
        traceback.print_exc()
        logger.error(f"Error during deleteUser: {str(e)}")
        connection.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during deleteUser: {str(e)}"
        )
    finally:
        close_db_connection(connection)


@router.get("/notice")
def get_user_notice():
    """
    유저 공지사항 전체 조회 API
    notice_user 테이블에서 모든 공지사항을 읽어옵니다.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''
            SELECT id, title, content, created_at, updated_at
            FROM notice_user
            ORDER BY created_at DESC
        ''')
        
        notices = cursor.fetchall()
        
        # 날짜 형식 변환
        for notice in notices:
            if notice.get('created_at'):
                notice['created_at'] = notice['created_at'].isoformat()
            if notice.get('updated_at'):
                notice['updated_at'] = notice['updated_at'].isoformat()
        
        return {
            "notices": notices,
            "total": len(notices)
        }
        
    except Exception as e:
        print(f"Error during get_user_notice: {e}")
        traceback.print_exc()
        logger.error(f"Error during get_user_notice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during get_user_notice: {str(e)}"
        )
    finally:
        cursor.close()
        close_db_connection(connection)


@router.post("/find-account")
def find_account(request: FindAccountRequest):
    """
    아이디 찾기 / 비밀번호 찾기 검증 API
    
    - type이 "find_id"인 경우: 이름과 전화번호가 맞으면 이메일(아이디) 반환
    - type이 "find_password"인 경우: 이름과 전화번호가 맞는지 검증만 수행
    
    Firebase 이메일 가입 유저만 지원합니다.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. DB에서 이름과 전화번호로 유저 조회
        cursor.execute('''
            SELECT id, name, email, phone, uid
            FROM user
            WHERE name = %s AND phone = %s
        ''', (request.name, request.phone_number))
        
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="입력하신 정보와 일치하는 계정을 찾을 수 없습니다."
            )
        
        # 2. Firebase에서 해당 uid의 유저 정보 확인
        try:
            user_app = get_user_firebase_app()
            user_record = auth.get_user(user['uid'], app=user_app)
            
            # Firebase 이메일 가입 유저인지 확인
            if not user_record.email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="이메일로 가입한 계정만 조회할 수 있습니다."
                )
            
            # 이메일 가입 방식인지 확인 (provider가 password인지 확인)
            providers = [provider.provider_id for provider in user_record.provider_data]
            if 'password' not in providers:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="이메일로 가입한 계정만 조회할 수 있습니다."
                )
            
        except firebase_admin.exceptions.NotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Firebase에서 해당 계정을 찾을 수 없습니다."
            )
        except Exception as e:
            logger.error(f"Firebase user lookup error: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"계정 확인 중 오류가 발생했습니다: {str(e)}"
            )
        
        # 3. type에 따라 응답 반환
        if request.type == "find_id":
            # 아이디 찾기: 이메일 반환 (일부 마스킹)
            email = user_record.email
            # 이메일 마스킹 처리 (예: abc@example.com -> ab***@example.com)
            if '@' in email:
                local_part, domain = email.split('@', 1)
                if len(local_part) > 2:
                    masked_email = local_part[:2] + '*' * (len(local_part) - 2) + '@' + domain
                else:
                    masked_email = '*' * len(local_part) + '@' + domain
            else:
                masked_email = email
            
            return {
                "success": True,
                "type": "find_id",
                "email": masked_email,  # 마스킹된 이메일
                "full_email": email,  # 전체 이메일 (필요시)
                "message": "아이디를 찾았습니다."
            }
        
        elif request.type == "find_password":
            # 비밀번호 찾기: 검증만 수행 (성공 여부만 반환)
            return {
                "success": True,
                "type": "find_password",
                "verified": True,
                "message": "입력하신 정보가 확인되었습니다. 비밀번호를 재설정할 수 있습니다."
            }
        
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="type은 'find_id' 또는 'find_password'여야 합니다."
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during find_account: {e}")
        traceback.print_exc()
        logger.error(f"Error during find_account: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"계정 찾기 중 오류가 발생했습니다: {str(e)}"
        )
    finally:
        cursor.close()
        close_db_connection(connection)
