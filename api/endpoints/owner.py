from fastapi import APIRouter, HTTPException, status, Header, Depends, Query, Request
from fastapi import FastAPI

from fastapi import FastAPI
from typing import Union, Optional
from pydantic import BaseModel
from loguru import logger
import traceback
import re
from slowapi import Limiter
from slowapi.util import get_remote_address

import uuid
import pymysql
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from db.session import get_db_connection, close_db_connection
from core.s3_config import S3_CLIENT, BUCKET_NAME, TERMS_BUCKET_NAME

from models.owner import Owner
from models.owner import OwnerFind
from models.owner import OwnerFindPw
from models.owner import OwnerInquiry
from models.owner import OwnerInquiryResponse
from models.owner import OwnerTermsAgreeRequest
from models.push_token import PushTokenCreate, PushTokenUpdate
from app.fcm_service import send_fcm_notification_to_owner
from app.auth.auth_dependency import verify_firebase_token, verify_firebase_token_any
from crud import terms as terms_crud
from core.exceptions import InternalError
from crud import admin as admin_crud

from models.user import User
from schemas.settlement import AccountUpdateRequest
import httpx
import json
from datetime import datetime, timezone
from core.config import settings
import core.dreamsecurity as dreamsecurity
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/check-duplicate")
@limiter.limit("10/minute")
async def check_duplicate(
    request: Request,
    email: Optional[str] = Query(None),
    phone_number: Optional[str] = Query(None),
    user=Depends(verify_firebase_token),
):
    if email is None and phone_number is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email 또는 phone_number 중 하나 이상 전달해야 합니다."
        )

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        email_exists = False
        phone_exists = False

        if email is not None:
            if email.endswith("@gifnut.com"):
                cursor.execute("SELECT COUNT(*) as cnt FROM owner WHERE login_id = %s", (email,))
            else:
                cursor.execute("SELECT COUNT(*) as cnt FROM owner WHERE email = %s", (email,))
            email_exists = cursor.fetchone()["cnt"] > 0

        if phone_number is not None:
            cursor.execute("SELECT COUNT(*) as cnt FROM owner WHERE phone = %s", (phone_number,))
            phone_exists = cursor.fetchone()["cnt"] > 0

        return {"email_exists": email_exists, "phone_exists": phone_exists}

    except Exception as e:
        raise InternalError(e, "check_duplicate")
    finally:
        close_db_connection(connection)


@router.post("/register")
async def registerOwner(owner: Owner, user=Depends(verify_firebase_token)):
    """사장님 회원가입.

    앱은 사전에 /mok/client-info + mobileOK 표준창을 통해 본인확인을 완료한 뒤
    client_tx_id를 전달한다. 서버는 mok_client_tx에서 검증된 name/phone/birthdate/gender를
    조회하여 owner 테이블에 저장한다. 앱이 별도로 이 값들을 보내지 않는다.
    """
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            # 본인확인 결과 조회 (FOR UPDATE로 재사용 방지)
            cursor.execute(
                """
                SELECT verified_name, verified_phone, verified_birthdate, verified_gender,
                       verified_at, consumed_at
                FROM mok_client_tx
                WHERE client_tx_id = %s
                FOR UPDATE
                """,
                (owner.client_tx_id,)
            )
            tx = cursor.fetchone()
            if not tx:
                raise HTTPException(status_code=400, detail="유효하지 않은 clientTxId")
            if tx["verified_at"] is None:
                raise HTTPException(status_code=400, detail="본인확인이 완료되지 않았습니다.")
            if tx["consumed_at"] is not None:
                raise HTTPException(status_code=400, detail="이미 사용된 본인확인입니다.")

            cursor.execute(
                "INSERT INTO owner (name, login_id, email, uid, phone, birthdate, gender) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    tx["verified_name"],
                    owner.login_id,
                    owner.email,
                    owner.uid,
                    tx["verified_phone"],
                    tx["verified_birthdate"],
                    tx["verified_gender"],
                )
            )
            owner_id = cursor.lastrowid

            cursor.execute(
                "UPDATE mok_client_tx SET consumed_at = NOW() WHERE client_tx_id = %s",
                (owner.client_tx_id,)
            )
        connection.commit()

        print("owner_id", owner_id)
        return {'owner_id': owner_id}
    except HTTPException:
        raise
    except pymysql.err.IntegrityError as e:
        logger.error(f"서버 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일 또는 전화번호입니다."
        )
    except Exception as e:
        raise InternalError(e, "registerOwner")
    finally:
        close_db_connection(connection)

@router.get("/login/{uid}")
async def login(uid: str, user=Depends(verify_firebase_token)):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''SELECT * FROM owner WHERE uid=%s ;''', (uid,))
        user = cursor.fetchone()  # 한 행만 가져옴
        
        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if user:
            print("user:", user)
            return {
                'owner_id': user['id'],
                'name': user['name'],
                'phone_number': user['phone'],
                'login_id': user['login_id'],
                'email': user['email'],
            }
        else:
            return {
                'msg': "unregistered user",
                'owner_id': None,
                'name': None,
                'phone_number': None,
                'login_id': None,
                'email': None,
            }

    except Exception as e:
        raise InternalError(e, "ownerLogin")
    finally:
        close_db_connection(connection)


_OWNER_TERM_TYPE_TO_PREFIX = {
    "SERVICE": "partner_service_term",
    "MARKETING": "partner_marketing_term",
    "PRIVACY": "partner_privacy_term",
    "PRIVACY_CONSENT": "partner_privacy_consent_term",
    "LOCATION": "partner_location_term",
    "FEE": "partner_fee_term",
}
_TERM_TYPE_TO_CATEGORY = {
    "SERVICE": "service",
    "MARKETING": "marketing",
    "PRIVACY": "privacy",
    "PRIVACY_CONSENT": "privacy_consent",
    "LOCATION": "location",
    "FEE": "fee",
}

VALID_OWNER_TERM_TYPES = set(_OWNER_TERM_TYPE_TO_PREFIX.keys())


# ---------- 약관 동의 (사장님) ----------

@router.get("/terms/content")
def get_owner_term_content(
    term_type: str = Query(..., description="SERVICE | PRIVACY | MARKETING | PRIVACY_CONSENT | LOCATION | FEE"),
):
    """사장님 약관 본문 조회. DB에서 현재 시행 중인 최신 버전 확인 후 S3에서 HTML 반환."""
    term_type = term_type.upper()
    if term_type not in VALID_OWNER_TERM_TYPES:
        raise HTTPException(status_code=400, detail=f"term_type must be one of {sorted(VALID_OWNER_TERM_TYPES)}")

    connection = get_db_connection()
    try:
        info = terms_crud.get_owner_term_content_info(connection, term_type)
        if not info:
            raise HTTPException(status_code=404, detail="현재 시행 중인 약관 버전이 없습니다.")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "get_owner_term_content DB")
    finally:
        close_db_connection(connection)

    version = info["version"]
    prefix = _OWNER_TERM_TYPE_TO_PREFIX[term_type]
    filename = f"{prefix}_{version}.html"
    category = _TERM_TYPE_TO_CATEGORY[term_type]
    key = f"terms/owner/{category}/{filename}"

    try:
        obj = S3_CLIENT.get_object(Bucket=TERMS_BUCKET_NAME, Key=key)
        content = obj["Body"].read().decode("utf-8", errors="replace")
        return {"content": content, "term_type": term_type, "version": version}
    except Exception as e:
        err_str = str(e)
        err_lower = err_str.lower()
        if "nosuchkey" in err_lower or "404" in err_lower or "no such key" in err_lower:
            raise HTTPException(status_code=404, detail=f"약관 파일을 찾을 수 없습니다. key: {key}")
        if "accessdenied" in err_lower or "forbidden" in err_lower:
            raise HTTPException(status_code=403, detail="S3 access denied")
        traceback.print_exc()
        raise InternalError(e, "get_owner_term_content S3")


@router.get("/terms/presigned-url")
def get_owner_term_presigned_url(
    term_type: str = Query(..., description="SERVICE | PRIVACY | MARKETING | PRIVACY_CONSENT | LOCATION | FEE"),
):
    """사장님 약관 HTML 파일의 S3 presigned GET URL 반환."""
    term_type = term_type.upper()
    if term_type not in VALID_OWNER_TERM_TYPES:
        raise HTTPException(status_code=400, detail=f"term_type must be one of {sorted(VALID_OWNER_TERM_TYPES)}")

    connection = get_db_connection()
    try:
        info = terms_crud.get_owner_term_content_info(connection, term_type)
        if not info:
            raise HTTPException(status_code=404, detail="현재 시행 중인 약관 버전이 없습니다.")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "get_owner_term_presigned_url DB")
    finally:
        close_db_connection(connection)

    version = info["version"]
    prefix = _OWNER_TERM_TYPE_TO_PREFIX[term_type]
    filename = f"{prefix}_{version}.html"
    category = _TERM_TYPE_TO_CATEGORY[term_type]
    key = f"terms/owner/{category}/{filename}"

    try:
        url = S3_CLIENT.generate_presigned_url(
            'get_object',
            Params={"Bucket": TERMS_BUCKET_NAME, "Key": key},
            ExpiresIn=3600,
        )
        return {"url": url, "term_type": term_type, "version": version}
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "get_owner_term_presigned_url S3")


@router.get("/terms/current")
def get_owner_terms_current():
    """현재 시행 중인 약관 목록 (회원가입/재동의 화면 노출용)."""
    connection = get_db_connection()
    try:
        terms = terms_crud.get_current_terms(connection, "owner")
        return {"terms": terms}
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "get_owner_terms_current")
    finally:
        close_db_connection(connection)


@router.get("/{owner_id}/terms/status")
def get_owner_terms_status(owner_id: int):
    """사장님의 약관별 동의 상태 및 재동의 필요 여부. 공지만 약관은 시행일 지나면 자동 저장."""
    connection = get_db_connection()
    try:
        result = terms_crud.get_owner_terms_status(connection, owner_id)
        return result
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "get_owner_terms_status")
    finally:
        close_db_connection(connection)


@router.post("/terms/agree")
def post_owner_terms_agree(body: OwnerTermsAgreeRequest):
    """약관 동의 저장 (회원가입/재동의 시). 필수 약관은 반드시 agreed=True."""
    connection = get_db_connection()
    try:
        agreements = [{"term_id": a.term_id, "term_version_id": a.term_version_id, "agreed": a.agreed} for a in body.agreements]
        success, err_msg, agreed_count = terms_crud.save_owner_agreements(connection, body.owner_id, agreements)
        if not success:
            raise HTTPException(status_code=400, detail=err_msg)
        return {"success": True, "message": "약관 동의가 저장되었습니다.", "agreed_count": agreed_count}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "post_owner_terms_agree")
    finally:
        close_db_connection(connection)


@router.post("/find_ownerId")
async def findOwnerId(owner: OwnerFind):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute('''SELECT * FROM owner WHERE name=%s AND phone=%s;''', (owner.name, owner.phone_number))
        user = cursor.fetchone()  # 한 행만 가져옴
        
        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if user:  # 사용자가 존재하는 경우
            print("user:", user)
            return {
                'owner_id': user['id'],
                'created_time': user['created_at'],
                'email': user['email'],
            }
        else:
            return {'msg': "unregistered user"}

    except Exception as e:
        raise InternalError(e, "findOwnerId")
    finally:
        close_db_connection(connection)

@router.post("/find_ownerPw")
async def findOwnerPW(owner: OwnerFindPw):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute(
            "SELECT * FROM owner WHERE login_id = %s AND phone = %s",
            (owner.login_id, owner.phone_number)
        )
        user = cursor.fetchone()  # 한 행만 가져옴
        
        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if user:  # 사용자가 존재하는 경우
            print("user:", user)
            return {
                'msg': 'success'
            }
        else:
            return {
                'msg': "fail", 
            }

    except Exception as e:
        print(e)
        result = {
            'msg': "An unexpected error occurred." + str(e),
        }
        return result
    finally:
        close_db_connection(connection)
        
@router.post("/inquiry/{owner_id}")
async def subjectInquiry(owner_id: int, inquiry: OwnerInquiry, user=Depends(verify_firebase_token)):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO owner_inquiry (owner_id, title, content) VALUES (%s, %s, %s)",
            (owner_id, inquiry.title, inquiry.content)
        )
        connection.commit()
                
        return {"message": "inquiry registered successfully"}
    except Exception as e:
        raise InternalError(e, "owner subjectInquiry")
    finally:
        close_db_connection(connection)

#사장님용.
@router.get("/inquiry/{owner_id}")
async def getInquiry(owner_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                 
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM owner_inquiry WHERE owner_id=%s ;''', (owner_id,))
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM owner_inquiry_response WHERE inquiry_id=%s ;''', (inquiry['id'],))
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
        raise InternalError(e, "owner getInquiry")
    finally:
        close_db_connection(connection)

#관리자용. 모든 문의내역 불러오기
@router.get("/inquiry")
async def getInquiry():
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM owner_inquiry;''')
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM owner_inquiry_response WHERE inquiry_id=%s;''', (inquiry['id'],))
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
                
        return {'inquiry_list': list(reversed(inquiry_list))}
    except Exception as e:
        raise InternalError(e, "owner getAllInquiry")
    finally:
        close_db_connection(connection)

@router.post("/reply/{inquiry_id}")
async def subjectInquiry(inquiry_id: int, reply: OwnerInquiryResponse):
    connection = get_db_connection()  # 환경에 맞는 DB 연결               
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. owner_inquiry 정보 조회 (owner_id, title 가져오기)
        cursor.execute('''
            SELECT owner_id, title 
            FROM owner_inquiry 
            WHERE id = %s
        ''', (inquiry_id,))
        inquiry = cursor.fetchone()
        
        if not inquiry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Owner inquiry with id {inquiry_id} not found"
            )
        
        owner_id = inquiry['owner_id']
        inquiry_title = inquiry['title']
        
        # 2. 기존 답변 확인
        cursor.execute('SELECT id FROM owner_inquiry_response WHERE inquiry_id = %s', (inquiry_id,))
        existing_response = cursor.fetchone()
        
        if existing_response:
            # 기존 답변이 있으면 UPDATE
            cursor.execute('''
                UPDATE owner_inquiry_response 
                SET response = %s, updated_at = NOW()
                WHERE inquiry_id = %s
            ''', (reply.response, inquiry_id))
        else:
            # 기존 답변이 없으면 INSERT
            cursor.execute('''
                INSERT INTO owner_inquiry_response (inquiry_id, response)
                VALUES (%s, %s)
            ''', (inquiry_id, reply.response))
        
        # 3. owner_inquiry 테이블의 status를 'answered'로 변경
        query_update_status = """
            UPDATE owner_inquiry
            SET status = 'answered'
            WHERE id = %s;
        """
        cursor.execute(query_update_status, (inquiry_id,))
        
        # 변경 사항을 커밋
        connection.commit()
        
        # 4. FCM 푸시 메시지 전송
        try:
            send_fcm_notification_to_owner(
                owner_id=owner_id,
                title="문의 답변이 등록되었습니다",
                body=f"[{inquiry_title}] 문의에 대한 답변이 등록되었습니다."
            )
        except Exception as fcm_error:
            logger.error(f"Failed to send FCM notification: {str(fcm_error)}")
            # FCM 전송 실패해도 답변은 성공한 것으로 처리
        
        return {"message": "reply registered successfully"}
    except Exception as e:
        raise InternalError(e, "owner subjectReply")
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

@router.post("/push-token/{owner_id}")
async def registerOwnerPushToken(
    owner_id: int,
    push_token: PushTokenCreate,
    user_agent: Optional[str] = Header(None, alias="User-Agent")
):
    """
    처음 가입 시 owner push token 정보를 저장하는 API
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
            SELECT id FROM owner_push_tokens
            WHERE owner_id = %s AND device_type = %s
        ''', (owner_id, push_token.device_type.value))
        existing = cursor.fetchone()

        if existing:
            cursor.execute('''
                UPDATE owner_push_tokens
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
                INSERT INTO owner_push_tokens (
                    owner_id, fcm_token, device_type,
                    allow_service_push, allow_marketing_push,
                    app_version, os_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                owner_id,
                push_token.fcm_token,
                push_token.device_type.value,
                1 if push_token.allow_service_push else 0,
                1 if push_token.allow_marketing_push else 0,
                app_version,
                os_version
            ))
        
        connection.commit()
        
        return {
            "message": "Owner push token registered successfully",
            "owner_id": owner_id
        }
        
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "registerOwnerPushToken")
    finally:
        cursor.close()
        close_db_connection(connection)

@router.delete("/push-token/{owner_id}")
async def deleteOwnerPushToken(
    owner_id: int,
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
            DELETE FROM owner_push_tokens
            WHERE owner_id = %s AND fcm_token = %s
        ''', (owner_id, fcm_token))
        connection.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Push token not found"
            )

        return {"message": "Owner push token deleted successfully", "owner_id": owner_id}

    except HTTPException:
        raise
    except Exception as e:
        raise InternalError(e, "deleteOwnerPushToken")
    finally:
        cursor.close()
        close_db_connection(connection)


@router.patch("/push-token/{owner_id}")
async def updateOwnerPushTokenAgreement(
    owner_id: int,
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
        
        update_values.extend([owner_id, fcm_token])
        
        query = f'''
            UPDATE owner_push_tokens 
            SET {', '.join(update_fields)}
            WHERE owner_id = %s AND fcm_token = %s
        '''
        
        cursor.execute(query, update_values)
        connection.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Push token not found"
            )
        
        return {
            "message": "Owner push token agreement updated successfully",
            "owner_id": owner_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "updateOwnerPushTokenAgreement")
    finally:
        cursor.close()
        close_db_connection(connection)

@router.delete("/{owner_id}")
async def deleteOwner(owner_id: int, user=Depends(verify_firebase_token_any)):
    """
    사장님 회원 탈퇴 API (Soft Delete)
    owner_id에 해당하는 사장님 정보를 soft delete 처리
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        # 1. 사장님 존재 여부 확인 (이미 삭제된 것은 제외)
        cursor.execute('SELECT id FROM owner WHERE id = %s AND (deleted_at IS NULL OR deleted_at = "")', (owner_id,))
        owner_record = cursor.fetchone()
        
        if not owner_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Owner with id {owner_id} not found or already deleted"
            )
        
        # 2. 관련 데이터 삭제 (push tokens)
        cursor.execute('DELETE FROM owner_push_tokens WHERE owner_id = %s', (owner_id,))
        
        # 3. Soft Delete: 민감정보 제거 및 deleted_at 설정
        cursor.execute('''
            UPDATE owner
            SET name = '',
                email = '',
                uid = '',
                phone_number = '',
                deleted_at = NOW()
            WHERE id = %s
        ''', (owner_id,))
        
        connection.commit()
        
        logger.info(f"Owner {owner_id} soft deleted successfully")
        
        return {
            "message": "Owner deleted successfully",
            "owner_id": owner_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        connection.rollback()
        traceback.print_exc()
        raise InternalError(e, "deleteOwner")
    finally:
        cursor.close()
        close_db_connection(connection)


@router.get("/statistics/{store_id}")
def get_store_statistics(store_id: int):
    """매장 통계 데이터 조회 (발행 수, 사용 수, 미사용 수)"""
    connection = get_db_connection()
    try:
        from crud import settlement as settlement_crud
        result = settlement_crud.get_store_statistics(store_id)
        return result
    except Exception as e:
        raise InternalError(e, "get_store_statistics")
    finally:
        close_db_connection(connection)


@router.get("/account/{store_id}")
def get_account_by_store(store_id: int):
    """store_id에 등록된 계좌 정보 조회"""
    connection = get_db_connection()
    try:
        from crud import settlement as settlement_crud
        account = settlement_crud.get_account_by_store(store_id)
        if not account:
            return {"account": {}}
        return {"account": account}
    except Exception as e:
        raise InternalError(e, "get_account_by_store")
    finally:
        close_db_connection(connection)


@router.put("/account/{store_id}")
def update_account(store_id: int, account: AccountUpdateRequest):
    """계좌 정보 변경 (예금주·은행·계좌번호 형식 검증 후 반영)"""
    connection = get_db_connection()
    try:
        from crud import settlement as settlement_crud
        from models.settlement import Account

        account_obj = Account(
            name=account.name,
            code=account.code,
            bank=account.bank,
            account=account.account,
        )
        settlement_crud.update_account(store_id, account_obj)

        s3 = S3_CLIENT
        bucket_name = BUCKET_NAME
        bankbook_key = f'bankbook/bankbook_{store_id}_{uuid.uuid4().hex[:8]}.png'
        conn2 = get_db_connection()
        try:
            cur2 = conn2.cursor()
            cur2.execute("UPDATE store SET bankbook_key = %s WHERE id = %s", (bankbook_key, store_id))
            conn2.commit()
        finally:
            conn2.close()
        bank_book_put_url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket_name, "Key": bankbook_key},
            ExpiresIn=3600,
        )
        return {
            "message": "Account updated successfully",
            "bank_book_put_url": bank_book_put_url,
        }
    except Exception as e:
        raise InternalError(e, "update_account")
    finally:
        close_db_connection(connection)


@router.get("/settlement/preview/{store_id}")
def get_owner_settlement_preview(store_id: int):
    """진행 중인 정산 주기 미리보기 상세: settlement_id가 null인 PENDING 항목 상세 조회용"""
    try:
        from crud import settlement as settlement_crud
        data = settlement_crud.get_owner_settlement_preview(store_id)
        if data is None:
            raise HTTPException(status_code=404, detail="진행 중인 정산 주기가 없거나 매출 데이터가 없습니다.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise InternalError(e, "get_owner_settlement_preview")


@router.get("/settlement/{store_id}")
def get_owner_settlement_data(
    store_id: int,
    past_months: int = Query(3, description="과거 몇 달 기준으로 정산 목록 조회 (1~24)", ge=1, le=24),
):
    """사장님 정산 목록. 과거 N달 기준은 쿼리 파라미터 past_months로 지정 (기본 3)."""
    try:
        from crud import settlement as settlement_crud
        items = settlement_crud.get_owner_settlement_list_unified(store_id, past_months=past_months)
        return {'settlements': items}
    except Exception as e:
        raise InternalError(e, "get_owner_settlement_data")


@router.get("/settlement/detail/{settlement_id}")
def get_owner_settlement_detail(settlement_id: int, user=Depends(verify_firebase_token_any)):
    """사장님 정산 상세: settlement 헤더 + details 건별 내역"""
    try:
        from crud import settlement as settlement_crud
        data = settlement_crud.get_owner_settlement_detail(settlement_id)
        if data is None:
            raise HTTPException(status_code=404, detail="해당 정산을 찾을 수 없습니다.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise InternalError(e, "get_owner_settlement_detail")


@router.get("/list/{owner_id}")
def get_owner_store_list(owner_id: int):
    """사장님의 매장 리스트 조회
    
    owner_id로 해당 사장님의 모든 매장 리스트를 반환합니다.
    """
    connection = get_db_connection()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    # S3 설정
    s3 = S3_CLIENT
    bucket_name = BUCKET_NAME
    
    try:
        # owner_id 존재 확인
        cursor.execute('SELECT id FROM owner WHERE id = %s', (owner_id,))
        owner = cursor.fetchone()
        
        if not owner:
            raise HTTPException(status_code=404, detail="Owner not found")
        
        # 해당 owner_id의 모든 매장 조회
        cursor.execute('''
            SELECT
                s.id,
                s.owner_id,
                s.store_name,
                s.store_telephone,
                s.store_description,
                s.store_address,
                s.store_lat,
                s.store_lng,
                s.region_code,
                s.district_code,
                s.inspection_status,
                s.inspection_msg,
                s.status,
                s.open_yn,
                s.created_at,
                s.updated_at,
                s.store_logo_key
            FROM store s
            WHERE s.owner_id = %s
            ORDER BY s.created_at DESC
        ''', (owner_id,))
        
        stores = cursor.fetchall()
        
        # 결과 포맷팅 (S3 이미지 URL 포함)
        store_list = []
        for store in stores:
            store_logo_key = store.get('store_logo_key')
            store_logo_url = s3.generate_presigned_url('get_object',
                Params={'Bucket': bucket_name, 'Key': store_logo_key},
                ExpiresIn=3600) if store_logo_key else None

            store_data = {
                'store_id': store['id'],
                'owner_id': store['owner_id'],
                'store_name': store['store_name'],
                'store_logo': store_logo_url,
                'store_telephone': store.get('store_telephone'),
                'store_description': store.get('store_description'),
                'store_address': store.get('store_address'),
                'store_lat': float(store['store_lat']) if store.get('store_lat') else None,
                'store_lng': float(store['store_lng']) if store.get('store_lng') else None,
                'region_code': store.get('region_code'),
                'district_code': store.get('district_code'),
                'inspection_status': store.get('inspection_status'),
                'inspection_msg': store.get('inspection_msg'),
                'status': store.get('status'),
                'open_yn': store.get('open_yn'),
                'created_at': store['created_at'].isoformat() if store.get('created_at') else None,
                'updated_at': store['updated_at'].isoformat() if store.get('updated_at') else None
            }
            store_list.append(store_data)
        
        return {
            'owner_id': owner_id,
            'store_count': len(store_list),
            'stores': store_list
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise InternalError(e, "get_owner_store_list")
    finally:
        cursor.close()
        close_db_connection(connection)


@router.get("/notice")
def get_owner_notice(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    """사장님 공지사항 목록 조회 (페이지네이션)"""
    connection = get_db_connection()
    try:
        result = admin_crud.get_notices(connection, target='owner', page=page, limit=limit)
        items = [{"id": n["id"], "title": n["title"], "created_at": n["created_at"]} for n in result["items"]]
        return {
            "message": "공지사항 목록 조회 성공",
            "data": items,
            "pagination": {
                "total": result["total"],
                "page": result["page"],
                "limit": result["limit"],
                "total_pages": result["total_pages"]
            }
        }
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "get_owner_notice")
    finally:
        close_db_connection(connection)


@router.get("/notice/{notice_id}")
def get_owner_notice_detail(notice_id: int):
    """사장님 공지사항 상세 조회"""
    connection = get_db_connection()
    try:
        notice = admin_crud.get_notice_detail(connection, target='owner', notice_id=notice_id)
        if not notice:
            raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
        return {
            "message": "공지사항 상세 조회 성공",
            "data": {
                "id": notice["id"],
                "title": notice["title"],
                "content": notice["content"],
                "created_at": notice["created_at"],
                "updated_at": notice["updated_at"]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "get_owner_notice_detail")
    finally:
        close_db_connection(connection)

# ── mobileOK 본인확인 (드림시큐리티 표준창) ──────────────────────────────────

@router.get("/mok/test-page")
def mok_test_page():
    """드림시큐리티 표준창 시작 - 서버에서 파라미터 조립 후 표준창 URL로 직접 리다이렉트.

    JS SDK의 동기 XHR 대신 서버가 직접 MOKReqClientInfo를 만들어
    ptb_mokauth.html에 쿼리스트링으로 전달한다.
    앱/브라우저 모두 동일하게 동작.
    """
    is_dev = "scert" in settings.mok_result_url
    base_url = "https://scert.mobile-ok.com" if is_dev else "https://cert.mobile-ok.com"

    keyinfo = dreamsecurity.get_keyinfo(settings.mok_keyinfo_path, settings.mok_keyinfo_password)
    service_id = keyinfo["ServiceId"]
    server_public_key = keyinfo["ServerPublicKey"]

    client_tx_id = f"GFN-{uuid.uuid4().hex[:32]}"
    request_time = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    json_data = json.dumps({
        "version": "V2",
        "clientTxId": client_tx_id,
        "requestTime": request_time,
    }, separators=(",", ":"))
    encrypt_req_client_info = dreamsecurity.encrypt_client_info(json_data, server_public_key)

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO mok_client_tx (client_tx_id, used) VALUES (%s, 0)",
                (client_tx_id,)
            )
        connection.commit()
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "mok_test_page DB insert")
    finally:
        close_db_connection(connection)

    from urllib.parse import urlencode
    # returnUrl에 clientTxId 포함 → 드림시큐리티가 콜백 시 그대로 전달
    return_url_with_tx = f"{settings.mok_return_url}?clientTxId={client_tx_id}"
    params = urlencode({
        "usageCode": "01001",
        "serviceId": service_id,
        "returnUrl": return_url_with_tx,
        "encryptVersion": "V2",
        "encryptReqClientInfo": encrypt_req_client_info,
        "serviceType": "telcoAuth",
        "retTransferType": "MOKToken",
        "callbackFunction": "",
        "alternative": "www.502company.com",
    })
    redirect_url = f"{base_url}/ptb_mokauth.html?{params}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/mok/client-info")
def mok_client_info():
    """드림시큐리티 표준창 거래 요청 정보 생성 (MOKReqClientInfo)

    응답 body 자체가 MOBILEOK.process()에 전달될 MOKReqClientInfo JSON이다.
    (개발가이드 표준창 V3 - 2. 거래요청정보 생성 스펙 준수)
    """
    keyinfo = dreamsecurity.get_keyinfo(settings.mok_keyinfo_path, settings.mok_keyinfo_password)
    service_id = keyinfo["ServiceId"]
    server_public_key = keyinfo["ServerPublicKey"]

    client_tx_id = f"GFN-{uuid.uuid4().hex[:32]}"  # 4 + 1 + 32 = 37자
    request_time = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    json_data = json.dumps({
        "version": "V2",
        "clientTxId": client_tx_id,
        "requestTime": request_time,
    }, separators=(",", ":"))

    encrypt_req_client_info = dreamsecurity.encrypt_client_info(json_data, server_public_key)

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO mok_client_tx (client_tx_id, used) VALUES (%s, 0)",
                (client_tx_id,)
            )
        connection.commit()
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "mok_client_info DB insert")
    finally:
        close_db_connection(connection)

    return {
        "serviceId": service_id,
        "encryptReqClientInfo": encrypt_req_client_info,
        "serviceType": "telcoAuth",
        "usageCode": "01001",
        "retTransferType": "MOKToken",
        "returnUrl": settings.mok_return_url,
        "encryptVersion": "V2",
        "clientTxId": client_tx_id,
    }


@router.post("/mok/return")
async def mok_return(request: Request, clientTxId: Optional[str] = Query(None)):
    """드림시큐리티 표준창 결과 수신.

    clientTxId는 returnUrl 쿼리스트링으로 전달됨 (?clientTxId=...).
    encryptMOKKeyToken은 form data의 data 필드(URL-encoded JSON)에 포함됨.
    """
    from urllib.parse import unquote
    form = await request.form()
    data_raw = form.get("data")
    if not data_raw:
        raise HTTPException(status_code=400, detail="data 파라미터 없음")

    try:
        mok_data = json.loads(unquote(str(data_raw)))
    except Exception:
        raise HTTPException(status_code=400, detail="data JSON 파싱 실패")

    encrypt_mok_key_token = mok_data.get("encryptMOKKeyToken")
    client_tx_id = clientTxId  # returnUrl 쿼리스트링에서 읽음

    if not encrypt_mok_key_token or not client_tx_id:
        raise HTTPException(status_code=400, detail="필수 파라미터 누락")


    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT used FROM mok_client_tx WHERE client_tx_id = %s FOR UPDATE",
                (client_tx_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail="유효하지 않은 clientTxId")
            if row["used"]:
                raise HTTPException(status_code=400, detail="이미 사용된 clientTxId")

            cursor.execute(
                "UPDATE mok_client_tx SET used = 1 WHERE client_tx_id = %s",
                (client_tx_id,)
            )
        connection.commit()

        # 드림시큐리티 검증 서버에 토큰 전달
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.mok_result_url,
                json={"encryptMOKKeyToken": encrypt_mok_key_token},
            )
            resp.raise_for_status()
            verify_result = resp.json()

        logger.info(f"[mok_return] verify_result keys: {list(verify_result.keys())}")
        logger.info(f"[mok_return] verify_result: {json.dumps(verify_result, ensure_ascii=False)[:500]}")
        encrypt_mok_result = verify_result.get("encryptMOKResult")
        if not encrypt_mok_result:
            raise HTTPException(status_code=502, detail=f"드림시큐리티 검증 서버 응답 오류: {verify_result}")

        # encryptMOKResult 복호화
        keyinfo = dreamsecurity.get_keyinfo(settings.mok_keyinfo_path, settings.mok_keyinfo_password)
        person_info = dreamsecurity.decrypt_mok_result(encrypt_mok_result, keyinfo["ClientPrivateKey"])

        verified_name = person_info.get("userName")
        verified_phone = person_info.get("userPhone")
        verified_gender = person_info.get("userGender")  # "M" 또는 "F"
        verified_birthdate = person_info.get("userBirthday")  # YYYYMMDD (VARCHAR(8))

        # mok_client_tx에 검증 결과 저장 (register 시점에 owner로 복사)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE mok_client_tx
                SET verified_name = %s,
                    verified_phone = %s,
                    verified_birthdate = %s,
                    verified_gender = %s,
                    verified_at = NOW()
                WHERE client_tx_id = %s
                """,
                (verified_name, verified_phone, verified_birthdate, verified_gender, client_tx_id)
            )
        connection.commit()

        # 앱이 NavigationDelegate로 감지할 수 있는 결과 URL로 리다이렉트
        # 브라우저(웹 테스트)에서는 JSON 반환
        prefix = "/dev" if "scert" in settings.mok_result_url else "/prod"
        redirect_url = f"{prefix}/owner/mok/result?clientTxId={client_tx_id}&resultCode=2000"
        return RedirectResponse(url=redirect_url, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise InternalError(e, "mok_return")
    finally:
        close_db_connection(connection)


@router.get("/mok/result", response_class=HTMLResponse)
def mok_result(clientTxId: str = Query(...), resultCode: str = Query(...)):
    """본인확인 완료 결과 페이지.

    앱은 NavigationDelegate에서 /mok/result URL 패턴을 감지하여
    clientTxId와 resultCode 파라미터를 읽는다.
    resultCode 2000 = 성공.
    """
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>본인확인 완료</title>
</head>
<body>
<p>본인확인이 완료되었습니다.</p>
<script>
// 앱 NavigationDelegate가 이 URL을 감지하지 못한 경우를 위한 폴백
var params = new URLSearchParams(window.location.search);
console.log('clientTxId:', params.get('clientTxId'));
console.log('resultCode:', params.get('resultCode'));
</script>
</body>
</html>"""
