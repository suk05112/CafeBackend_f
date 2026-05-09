import firebase_admin
from firebase_admin import credentials
import os

# Firebase 인증서 파일 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# 사용자 앱 (User App) Firebase 인증서 파일 경로
user_firebase_cred_path = os.getenv(
    "USER_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "cafeplatform-firebase-adminsdk-oq7t0-930245c6eb.json")  # 기본값: 기존 파일
)

# 사장님 앱 (Owner App) Firebase 인증서 파일 경로
owner_firebase_cred_path = os.getenv(
    "OWNER_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "cafe-owner-firebase-adminsdk-4pxe9-e44664feb1.json")
)

# Dev 앱 Firebase 인증서 파일 경로
dev_firebase_cred_path = os.getenv(
    "DEV_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "gifnut-dev-firebase-adminsdk-fbsvc-38860a44e8.json")
)

print("initialize firebase")

# 사용자 앱 초기화
if not firebase_admin._apps:
    user_cred = credentials.Certificate(user_firebase_cred_path)
    firebase_admin.initialize_app(user_cred, name="user_app")
    print(f"✅ User App Firebase initialized: {user_firebase_cred_path}")

# 사장님 앱 Firebase 초기화
try:
    if not any(app.name == "owner_app" for app in firebase_admin._apps if hasattr(app, 'name')):
        owner_cred = credentials.Certificate(owner_firebase_cred_path)
        firebase_admin.initialize_app(owner_cred, name="owner_app")
        print(f"✅ Owner App Firebase initialized: {owner_firebase_cred_path}")
    else:
        print("⚠️  Owner App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  Owner App Firebase credentials not found: {owner_firebase_cred_path}")
except Exception as e:
    print(f"⚠️  Owner App Firebase initialization failed: {str(e)}")

# Dev 앱 Firebase 초기화
try:
    if not any(app.name == "dev_app" for app in firebase_admin._apps if hasattr(app, 'name')):
        dev_cred = credentials.Certificate(dev_firebase_cred_path)
        firebase_admin.initialize_app(dev_cred, name="dev_app")
        print(f"✅ Dev App Firebase initialized: {dev_firebase_cred_path}")
    else:
        print("⚠️  Dev App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  Dev App Firebase credentials not found: {dev_firebase_cred_path}")
except Exception as e:
    print(f"⚠️  Dev App Firebase initialization failed: {str(e)}")
