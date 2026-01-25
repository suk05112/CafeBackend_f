from fastapi import Request, Header, HTTPException, Depends
from firebase_admin import auth, app_check
import firebase_admin
import logging
import traceback

# CloudWatch에 직접 로깅하는 logger 사용 (main.py와 동일)
logger = logging.getLogger("cafe_backend")


def get_firebase_app(project_type: str = "user"):
    """
    프로젝트 타입에 따라 Firebase 앱 반환
    - "user": 사용자 앱 (기본값)
    - "owner": 사장님 앱
    """
    if project_type == "owner":
        try:
            # 사장님 앱 반환
            return firebase_admin.get_app("owner_app")
        except ValueError:
            # owner_app이 없으면 에러
            raise ValueError(f"Firebase owner_app not initialized. Check firebase_init.py and ensure OWNER_FIREBASE_CRED_PATH is set.")
    else:
        # 사용자 앱 (기본 앱 또는 user_app)
        try:
            # user_app 이름으로 시도
            return firebase_admin.get_app("user_app")
        except ValueError:
            # user_app이 없으면 기본 앱 반환 (기존 호환성)
            return firebase_admin.get_app()


async def verify_firebase_token(request: Request,
    authorization: str = Header(None),
    app_check_token: str = Header(None, alias="X-Firebase-AppCheck"),
    firebase_project: str = Header(None, alias="X-Firebase-Project")):
 
    ua = request.headers.get("User-Agent", "")

    # 웹 요청이면 인증 패스
    if "Mozilla" in ua or not ua:
        return None
    
    # 프로젝트 타입 결정 (기본값: user)
    project_type = "owner" if firebase_project and firebase_project.lower() == "owner" else "user"
    
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
        # 예상치 못한 예외
        error_traceback = traceback.format_exc()
        logger.error(f"verify_firebase_token - Unexpected error: {str(e)}\n{error_traceback} | URL: {request.url.path} | Method: {request.method}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")
