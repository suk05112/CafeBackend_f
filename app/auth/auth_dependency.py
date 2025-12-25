from fastapi import Request, Header, HTTPException, Depends
from firebase_admin import auth
from firebase_admin import app_check


# def verify_firebase_token(authorization: str = Header(None), app_check_token: str = Header(None, alias="X-Firebase-AppCheck")):
async def verify_firebase_token(request: Request,
    authorization: str = Header(None),
    app_check_token: str = Header(None, alias="X-Firebase-AppCheck")):
 
    return None
    ua = request.headers.get("User-Agent", "")

    # 웹 요청이면 인증 패스
    if "Mozilla" in ua or not ua:
        return None
    
    # token = authorization.headers.get("X-Firebase-AppCheck") 
    print("app_check_token", app_check_token)
    print("\n")
    
    if not authorization or not authorization.startswith("Bearer "):
        # Bearer 토큰이 없으면 App Check 토큰 확인
        if not app_check_token:
            raise HTTPException(status_code=401, detail="Missing App Check token")
        else:
            decoded = app_check.verify_token(app_check_token) # SDK or REST 
            print("appcheck decode", decoded)
            print("\n")
            return decoded

    # Bearer 토큰이 있으면 ID 토큰 검증
    id_token = authorization.split(" ")[1]

    try:
        decoded = auth.verify_id_token(id_token)
        return decoded  # uid, email, name 등
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
