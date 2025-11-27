from fastapi import Request, Header, HTTPException, Depends
from firebase_admin import auth
from firebase_admin import app_check


# def verify_firebase_token(authorization: str = Header(None), app_check_token: str = Header(None, alias="X-Firebase-AppCheck")):
async def verify_firebase_token(request: Request,
    authorization: str = Header(None),
    app_check_token: str = Header(None, alias="X-Firebase-AppCheck")):
 
    ua = request.headers.get("User-Agent", "")

    # 1) 웹은 제외
    if "Mozilla" in ua:
        return
    
    # token = authorization.headers.get("X-Firebase-AppCheck") 
    print("app_check_token", app_check_token)
    print("\n")
    decoded = app_check.verify_token(app_check_token) # SDK or REST 
    print("appcheck decode", decoded)
    print("\n")


    ua = request.headers.get("User-Agent", "")


    if not authorization or not authorization.startswith("Bearer "):
        # raise HTTPException(status_code=401, detail="Token missing")

        if not app_check_token:
            raise HTTPException(status_code=401, detail="Missing App Check token")
        # if not token: 
            # raise HTTPException(401, "Missing App Check token") 
            # raise HTTPException(status_code=401, detail="Token missing")
        else:
            decoded = app_check.verify_token(app_check_token) # SDK or REST 
            return decoded

    id_token = authorization.split(" ")[1]

    try:
        decoded = auth.verify_id_token(id_token)
        return decoded  # uid, email, name 등
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
        # raise HTTPException(401, "Invalid App Check token")
