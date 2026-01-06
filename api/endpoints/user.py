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

from typing import Union
from pydantic import BaseModel

import pymysql
import app.database as databas
import boto3
from botocore.client import Config
from app.database import get_db_connection

import logging
logger = logging.getLogger("cafe_backend")

from models.user import User
from models.user import Inquiry
from models.user import InquiryResponse
from models.push_token import PushTokenCreate, PushTokenUpdate
from app.fcm_service import send_fcm_notification_to_user

router = APIRouter()

@router.post("/register")
def signUp(user: User):
    
    uid = user.uid

    user_record = auth.get_user(uid)
    print("user_record\n\n")
    print(user_record)
    
    # user_record의 모든 속성 출력
    print("\n=== user_record 모든 속성 ===")
    for attr in dir(user_record):
        if not attr.startswith('_'):
            try:
                value = getattr(user_record, attr)
                if not callable(value):
                    print(f"{attr}: {value}")
            except Exception as e:
                print(f"{attr}: (에러: {e})")

    email = user_record.email
    # 요청으로 받은 name을 사용, 없으면 Firebase의 display_name 사용
    name = user.name or user_record.display_name
    phone_number = user_record.phone_number 
    # provider는 User 모델에서 직접 가져오거나, firebase에서 가져오기
    provider = user.provider
    
    print("user", uid, email, name, phone_number, provider)
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO user (
                name, email, phone, uid
            ) VALUES (%s, %s, %s, %s);
        """
        # cursor.execute(query, ("name", "email", "phone_number"))

        cursor.execute(query, (name, email, phone_number, uid))
        connection.commit()

        user_id = cursor.lastrowid
        print(user_id)
        
        linkAccount(uid, user_id, provider, email)
        
        return {"user_id": user_id}
                                                  
    except Exception as e:
        print(e)
        raise
    finally:
        connection.close()
        
def linkAccount(uid, user_id, provider, email):
    print("linkAccount")
    user_record = auth.get_user(uid)
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
        check_query = """
            SELECT * FROM user_provider 
            WHERE user_id = %s AND email = %s AND provider = %s;
        """
        cursor.execute(check_query, (user_id, email, provider))
        existing = cursor.fetchone()
        
        if existing:
            print(f"이미 등록된 user_provider: user_id={user_id}, email={email}, provider={provider}")
            return
        
        query = """
            INSERT INTO user_provider (
                user_id, email, provider
            ) VALUES (%s, %s, %s);
        """

        cursor.execute(query, (user_id, email, provider))
        connection.commit()
                                                  
    except Exception as e:
        print(e)
        raise
    finally:
        connection.close()

@router.get("/login/{email}")
async def login_user(email: str, user=Depends(verify_firebase_token)):
    """
    Firebase 토큰 기반 로그인.
    클라이언트는 email을 보내지 않음.
    서버가 직접 Firebase 토큰에서 email, uid 읽음.
    """

    print(user)
    
    # user가 None인 경우 처리 (웹 요청 등)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    # email = user.get("email")
    uid = user.get("uid")
    # firebase 정보 안전하게 가져오기
    firebase_info = user.get("firebase") or {}
    provider = firebase_info.get("sign_in_provider") if firebase_info else None
    
    # provider가 "phone"이면 "email"로 치환
    if provider == "phone":
        provider = "email"
    
    # provider가 None인 경우 기본값 설정
    if provider is None:
        provider = "unknown"
    
    try:
        user_record = auth.get_user(uid)
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
    
    if email.endswith("@privaterelay.appleid.com"):
        provider = "apple.priavate"

    try:
        cursor.execute("SELECT * FROM user WHERE uid=%s;", (uid,))
        db_user = cursor.fetchone()
   
        cursor.execute("SELECT * FROM user_provider WHERE email=%s AND provider=%s;", (email, provider))
        islinked = cursor.fetchone()
        
        if email == "apple":
             islinked = True
        
        if db_user:
            user_id = db_user["id"]

            print("이미 등록 islinked", islinked)
            # 이미 등록된 유저
            
            if islinked is None:
                print("islinked false")
                linkAccount(uid, user_id, provider, email)
            else:
                print("islinked true")

            return {
                "isRegistered": 1,
                "user_id": db_user["id"],
                "name": db_user["name"],
                "email": db_user["email"],
                "phone_number": db_user["phone"],
            }
        else:
            print("미등록")

            # 아직 등록되지 않은 유저
            signUp(user)

            return {
                "isRegistered": 0,
                # "uid": uid,       # 고객 uid 제공
                "email": email,
            }

    except Exception as e:
        print("login 오류", e)
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"login failed: {str(e)}"
        )

    finally:
        connection.close()


@router.get("/isRegistered")
async def idRegisteredUser(
    email: str = Query(...),
    provider: str = Query(...),
    firebase = Depends(verify_firebase_token)
):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
    cursor = connection.cursor()

    try:
        cursor.execute('''SELECT * FROM user_provider WHERE email=%s AND provider=%s ;''', (email, provider))

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
        cursor.close()
        
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
        connection.close()

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
        connection.close()

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
        connection.close()

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
        connection.close()
        
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
        connection.close()

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
        
        # 기존 토큰이 있는지 확인
        cursor.execute('''
            SELECT id FROM user_push_tokens 
            WHERE user_id = %s AND fcm_token = %s
        ''', (user_id, push_token.fcm_token))
        existing = cursor.fetchone()
        
        if existing:
            # 기존 토큰이 있으면 업데이트
            cursor.execute('''
                UPDATE user_push_tokens 
                SET device_type = %s,
                    allow_service_push = %s,
                    allow_marketing_push = %s,
                    app_version = %s,
                    os_version = %s
                WHERE id = %s
            ''', (
                push_token.device_type.value,
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
        connection.close()

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
        connection.close()

@router.delete("/{user_id}")
async def deleteUser(user_id: int, user=Depends(verify_firebase_token)):
    """
    회원 탈퇴 API (Soft Delete)
    user_id에 해당하는 사용자 정보를 soft delete 처리
    - user_provider 테이블에서 user_id 삭제
    - user 테이블에서 email, phone, name 삭제 (빈 값으로 설정)
    - user 테이블에서 is_deleted = 1 설정
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. 사용자 존재 여부 확인 (이미 삭제된 것은 제외)
        cursor.execute('SELECT id FROM user WHERE id = %s AND (is_deleted IS NULL OR is_deleted = 0)', (user_id,))
        user_record = cursor.fetchone()
        
        if not user_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {user_id} not found or already deleted"
            )
        
        # 2. 관련 데이터 삭제
        # user_provider 테이블에서 user_id 삭제
        cursor.execute('DELETE FROM user_provider WHERE user_id = %s', (user_id,))
        
        # push tokens 삭제
        cursor.execute('DELETE FROM user_push_tokens WHERE user_id = %s', (user_id,))
        
        # 3. user 테이블 업데이트: 개인정보 삭제, is_deleted = 1, deleted_at = 현재시간 설정
        cursor.execute('''
            UPDATE user 
            SET email = '', 
                phone = '', 
                name = '', 
                is_deleted = 1,
                deleted_at = NOW()
            WHERE id = %s
        ''', (user_id,))
        
        connection.commit()
        
        logger.info(f"User {user_id} soft deleted successfully")
        
        return {
            "message": "User deleted successfully",
            "user_id": user_id
        }
        
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
        cursor.close()
        connection.close()

