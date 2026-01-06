from fastapi import Request, Header, HTTPException, Depends
from firebase_admin import auth
from firebase_admin import app_check
import logging
import traceback

# CloudWatch에 직접 로깅하는 logger 사용 (main.py와 동일)
logger = logging.getLogger("cafe_backend")


# def verify_firebase_token(authorization: str = Header(None), app_check_token: str = Header(None, alias="X-Firebase-AppCheck")):
async def verify_firebase_token(request: Request,
    authorization: str = Header(None),
    app_check_token: str = Header(None, alias="X-Firebase-AppCheck")):
 
    ua = request.headers.get("User-Agent", "")

    # 웹 요청이면 인증 패스
    if "Mozilla" in ua or not ua:
        return None
    
    # token = authorization.headers.get("X-Firebase-AppCheck") 
    print("app_check_token", app_check_token)
    print("\n")
    
    try:
        if not authorization or not authorization.startswith("Bearer "):
            # Bearer 토큰이 없으면 App Check 토큰 확인
            if not app_check_token:
                print("suji5 >> exception handler5")

                error_msg = "Missing App Check token"
                logger.error(f"verify_firebase_token error: {error_msg} | URL: {request.url.path} | Method: {request.method}")
                raise HTTPException(status_code=401, detail=error_msg)
            else:
                try:
                    decoded = app_check.verify_token(app_check_token) # SDK or REST 
                    print("appcheck decode", decoded)
                    print("\n")
                    return decoded
                except Exception as e:
                    print("suji4 >> exception handler4")

                    error_traceback = traceback.format_exc()
                    logger.error(f"verify_firebase_token - App Check token verification failed: {str(e)}\n{error_traceback} | URL: {request.url.path} | Method: {request.method}")
                    raise HTTPException(status_code=401, detail=f"App Check token verification failed: {str(e)}")

        # Bearer 토큰이 있으면 ID 토큰 검증
        id_token = authorization.split(" ")[1]

        try:
            decoded = auth.verify_id_token(id_token)
            return decoded  # uid, email, name 등
        except Exception as e:
            error_traceback = traceback.format_exc()
            logger.error(f"verify_firebase_token - ID token verification failed: {str(e)}\n{error_traceback} | URL: {request.url.path} | Method: {request.method}")
            raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        # HTTPException은 그대로 re-raise (이미 로깅됨)
        raise
    except Exception as e:
        # 예상치 못한 예외
        error_traceback = traceback.format_exc()
        logger.error(f"verify_firebase_token - Unexpected error: {str(e)}\n{error_traceback} | URL: {request.url.path} | Method: {request.method}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")
