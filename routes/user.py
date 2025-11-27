import traceback
from fastapi import FastAPI, Header, Query, Request, APIRouter, Depends, HTTPException
from auth.auth_dependency import verify_firebase_token
import firebase_admin
from firebase_admin import auth, credentials

from typing import Union
from pydantic import BaseModel

import pymysql
import app.database as databas
import boto3
from botocore.client import Config
from app.database import get_db_connection

from loguru import logger

from models.user import User
from models.user import Inquiry
from models.user import InquiryResponse

#상위폴더 참조
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

router = APIRouter()

@router.post("/register")
async def registerUser(user: User):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor()

    try:
        query = """
            INSERT INTO User (
                name, email, phone_number
            ) VALUES (%s, %s, %s);
        """

        cursor.execute(query, (user.name, user.email, user.phone_number))
        connection.commit()

        user_id = cursor.lastrowid
        print(user_id)
                                                  
        return {
            'statusCode': 200,
            'user_id': user_id
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register store - " + str(e),
            'store_id': -1
        }
        return result
    finally:
        connection.close()
        
def signUp(user: dict):
    
    uid = user.get("uid")

    user_record = auth.get_user(uid)
    print("user_record\n\n")
    print(user_record)
    
    print("=====user=====\n", user)

    print(user_record.email)
    print(user_record.phone_number)
    print(user_record.display_name)
    
    email = user_record.email
    name = user_record.display_name          # Firebase 토큰에 name이 없으면 None
    phone_number = user_record.phone_number 
    provider = user.get("firebase").get("sign_in_provider")  
    
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
                                                  
    except Exception as e:
        print(e)
    finally:
        connection.close()
        
def linkAccount(uid, user_id, provider, email):
    print("linkAccount")
    user_record = auth.get_user(uid)
    print("user_record\n\n")
    
    # email = user_record.email
    phone_number = user_record.phone_number 
    # provider = user.get("firebase").get("sign_in_provider")  
    
    print("user", uid, email, phone_number, provider)
    connection = get_db_connection()  # 환경에 맞는 DB 연결                      
    cursor = connection.cursor()
    
    try:
        print(user_id)
        
        query = """
            INSERT INTO user_provider (
                user_id, email, provider
            ) VALUES (%s, %s, %s);
        """

        cursor.execute(query, (user_id, email, provider))
        connection.commit()
                                                  
    except Exception as e:
        print(e)
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
    # email = user.get("email")
    uid = user.get("uid")
    provider = user.get("firebase").get("sign_in_provider")  
    
    user_record = auth.get_user(uid)
    email2 = user_record.email


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
                "statusCode": 200,
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
                "statusCode": 200,
                "isRegistered": 0,
                # "uid": uid,       # 고객 uid 제공
                "email": email,
            }

    except Exception as e:
        print("login 오류", e)

        return {
            "statusCode": 500,
            "msg": f"login failed {e}",
        }

    finally:
        connection.close()
        
# @router.get("/login/{email}")
# async def idRegisteredUser(email: str):
#     connection = get_db_connection()  # 환경에 맞는 DB 연결                      
#     cursor = connection.cursor(pymysql.cursors.DictCursor)

#     try:
#         cursor.execute('''SELECT * FROM User WHERE email=%s ;''', (email,))
#         user = cursor.fetchone()  # 한 행만 가져옴

#         # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
#         if user:  # 사용자가 존재하는 경우
#             print("user:", user)
#             return {
#                 'statusCode': 200,
#                 'user_id': user['user_id'],
#                 'name': user['name'],
#                 'email': user['email'],
#                 'phone_number': user['phone_number'],
#             }
#         else:
#             return {
#                 'statusCode': 200,
#                 'isRegistered': 0  # 이메일이 존재하지 않으면 0
#             }

#     except Exception as e:
#         print(e)
#         result = {
#             'statusCode': 500,
#             'msg': "failed login " + str(e),
#             'store_id': -1
#         }
#         return result
#     finally:
#         connection.close()


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
            return {
                'statusCode': 200,
                'isRegistered': True  # 이메일이 존재하면 1
            }
        else:
            return {
                'statusCode': 200,
                'isRegistered': False  # 이메일이 존재하지 않으면 0
            }

    except Exception as e:
        print("isRegistered 오류", e)
        result = {
            'statusCode': 500,
            'msg': "failed register store - " + str(e),
            'store_id': -1
        }
        return result
    finally:
        connection.close()
        
@router.get("/isRegistered/{phoneNumber}")
async def idRegisteredAppleUser(phoneNumber: str):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                     
    cursor = connection.cursor()

    try:
        cursor.execute('''SELECT * FROM user WHERE phone=%s;''', (phoneNumber))

        # 결과 확인 (1개 이상의 행이 반환되면 이메일이 존재)
        if cursor.fetchone():
            return {
                'statusCode': 200,
                'isRegistered': True  # 이메일이 존재하면 1
            }
        else:
            return {
                'statusCode': 200,
                'isRegistered': False  # 이메일이 존재하지 않으면 0
            }

    except Exception as e:
        print("isRegistered 오류", e)
        result = {
            'statusCode': 500,
            'msg': "failed register store - " + str(e),
            'store_id': -1
        }
        return result
    finally:
        connection.close()

@router.post("/inquiry/{user_id}")
async def subjectInquiry(user_id: int, inquiry: Inquiry):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO Inquiry (
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
                
        return {
            'statusCode': 200,
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register inquiry - " + str(e),
            }
        traceback.print_exc() 
        logger.error(f"Error: {str(e)} {result}")
        raise HTTPException(status_code=500, detail="failed register inquiry - " + str(e))

    finally:
        connection.close()

#유저용. 
@router.get("/inquiry/{user_id}")
async def getInquiry(user_id: int):
    connection = get_db_connection()  # 환경에 맞는 DB 연결                 
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM Inquiry WHERE user_id=%s ;''', (user_id,))
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM Inquiry_response WHERE id=%s ;''', (inquiry['id'],))
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
                
        return {
            'inquiry_list': list(reversed(inquiry_list))
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed get inquiry - " + str(e),
            }
        traceback.print_exc() 
        logger.error(f"Error: {str(e)} {result}")
        raise HTTPException(status_code=500, detail="failed get inquiry - " + str(e))

    finally:
        connection.close()

#모든 문의내역 불러오기
@router.get("/inquiry")
async def getInquiry():
    connection = get_db_connection()  # 환경에 맞는 DB 연결                
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute('''SELECT id, title, content, status, created_at FROM Inquiry;''')
        inquiries = cursor.fetchall()  
        
        inquiry_list = []
        
        for inquiry in inquiries:
            cursor.execute('''SELECT response, created_at FROM Inquiry_response WHERE id=%s;''', (inquiry['id'],))
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
                
        return {
            'inquiry_list': list(reversed(inquiry_list))
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed register inquiry - " + str(e),
            }
        traceback.print_exc() 
        logger.error(f"Error: {str(e)} {result}")
        raise HTTPException(status_code=500, detail="failed get all inquiry - " + str(e))

    finally:
        connection.close()
        
@router.post("/reply/{inquiry_id}")
async def subjectInquiry(inquiry_id: int, reply: InquiryResponse):
    connection = get_db_connection()  # 환경에 맞는 DB 연결               
    cursor = connection.cursor()
    
    try:
        query = """
            INSERT INTO Owner_Inquiry_response (
                inquiry_id, response
            ) VALUES (
              {}, '{}'
            );
        """.format(
            inquiry_id,
            reply.response,
            )
            
        cursor.execute(query)
        
        # Owner_Inquiry 테이블에서 해당 inquiry_id의 status를 'answered'로 변경하는 쿼리
        query_update_status = """
            UPDATE Owner_Inquiry
            SET status = 'answered'
            WHERE id = %s;
        """
        cursor.execute(query_update_status, (inquiry_id,))
        
        # 변경 사항을 커밋
        connection.commit()                
        return {
            'statusCode': 200,
        }
    except Exception as e:
        print(e)
        result = {
            'statusCode': 500,
            'msg': "failed subject inquiry - " + str(e),
            }
        return result
    finally:
        connection.close()