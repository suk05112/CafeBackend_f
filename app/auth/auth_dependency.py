from fastapi import Request, Header, HTTPException, Depends
from firebase_admin import auth, app_check
import firebase_admin
import logging
import traceback
from core.exceptions import InternalError

# CloudWatch에 직접 로깅하는 logger 사용 (main.py와 동일)
logger = logging.getLogger("cafe_backend")


def get_firebase_app(project_type: str = "user"):
    """
    프로젝트 타입에 따라 Firebase 앱 반환
    - "user": 사용자 앱 (기본값)
    - "owner": 사장님 앱
    - "dev": Dev 앱 (gifnut-dev)
    """
    if project_type == "owner":
        try:
            return firebase_admin.get_app("owner_app")
        except ValueError:
            raise ValueError("Firebase owner_app not initialized.")
    elif project_type == "dev":
        try:
            return firebase_admin.get_app("dev_app")
        except ValueError:
            raise ValueError("Firebase dev_app not initialized.")
    else:
        try:
            return firebase_admin.get_app("user_app")
        except ValueError:
            return firebase_admin.get_app()


async def verify_firebase_token(request: Request,
    authorization: str = Header(None),
    app_check_token: str = Header(None, alias="X-Firebase-AppCheck"),
    firebase_project: str = Header(None, alias="X-Firebase-Project")):

    has_token = (authorization and authorization.startswith("Bearer ")) or app_check_token
    if not has_token:
        client_ip = request.headers.get("X-Real-IP") or request.client.host
        if client_ip in {"118.42.1.29", "119.203.17.126", "16.184.58.200"}:
            return None

    # 프로젝트 타입 결정 (기본값: user)
    if firebase_project and firebase_project.lower() == "owner":
        project_type = "owner"
    elif firebase_project and firebase_project.lower() == "dev":
        project_type = "dev"
    else:
        project_type = "user"
    
    print(f"app_check_token: {app_check_token is not None}, project_type: {project_type}")
    print("\n")
    
    try:
        if not authorization or not authorization.startswith("Bearer "):
            # Bearer 토큰이 없으면 App Check 토큰 확인
            if not app_check_token:
                print("suji5 >> exception handler5")

                error_msg = "Missing App Check token"
                logger.error(f"verify_firebase_token error: {error_msg} | URL: {request.url.path} | Method: {request.method} | Project: {project_type}")
                raise HTTPException(status_code=401, detail=error_msg)
            else:
                try:
                    # 프로젝트 타입에 따라 적절한 Firebase 앱 사용
                    app = get_firebase_app(project_type)
                    decoded = app_check.verify_token(app_check_token, app=app)
                    print(f"appcheck decode ({project_type}): {decoded}")
                    print("\n")
                    return decoded
                except Exception as e:
                    print("suji4 >> exception handler4")

                    error_traceback = traceback.format_exc()
                    logger.error(f"verify_firebase_token - App Check token verification failed ({project_type}): {str(e)}\n{error_traceback} | URL: {request.url.path} | Method: {request.method}")
                    raise HTTPException(status_code=401, detail=f"App Check token verification failed: {str(e)}")

        # Bearer 토큰이 있으면 ID 토큰 검증
        id_token = authorization.split(" ")[1]

        try:
            # 프로젝트 타입에 따라 적절한 Firebase 앱 사용
            app = get_firebase_app(project_type)
            decoded = auth.verify_id_token(id_token, app=app)
            return decoded  # uid, email, name 등
        except Exception as e:
            error_traceback = traceback.format_exc()
            logger.error(f"verify_firebase_token - ID token verification failed ({project_type}): {str(e)}\n{error_traceback} | URL: {request.url.path} | Method: {request.method}")
            raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        # HTTPException은 그대로 re-raise (이미 로깅됨)
        raise
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"verify_firebase_token - Unexpected error: {str(e)}\n{error_traceback} | URL: {request.url.path} | Method: {request.method}")
        raise InternalError(e, "verify_firebase_token")


async def verify_firebase_token_any(
    request: Request,
    authorization: str = Header(None),
    app_check_token: str = Header(None, alias="X-Firebase-AppCheck"),
):
    """user 앱 또는 owner 앱 토큰 중 하나라도 유효하면 허용.
    X-Firebase-Project 헤더 없이 호출하는 owner 앱 클라이언트를 위한 의존성."""
    has_token = (authorization and authorization.startswith("Bearer ")) or app_check_token
    if not has_token:
        client_ip = request.headers.get("X-Real-IP") or request.client.host
        if client_ip in {"118.42.1.29", "119.203.17.126", "16.184.58.200"}:
            return None

    last_error = None
    for project_type in ("user", "owner"):
        try:
            app = get_firebase_app(project_type)
            if authorization and authorization.startswith("Bearer "):
                id_token = authorization.split(" ")[1]
                decoded = auth.verify_id_token(id_token, app=app)
                return decoded
            elif app_check_token:
                decoded = app_check.verify_token(app_check_token, app=app)
                return decoded
        except Exception as e:
            last_error = e
            continue

    error_msg = f"Token verification failed for both user and owner projects: {last_error}"
    logger.error(f"verify_firebase_token_any error: {error_msg} | URL: {request.url.path}")
    raise HTTPException(status_code=401, detail="Invalid or missing authentication token")
