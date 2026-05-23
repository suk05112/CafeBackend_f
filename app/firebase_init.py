import firebase_admin
from firebase_admin import credentials
import os

# Firebase 인증서 파일 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# 사용자 앱 (User App) Firebase 인증서 파일 경로
user_firebase_cred_path = os.getenv(
    "USER_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "cafeplatform-firebase-adminsdk-oq7t0-930245c6eb.json")
)

# 사장님 앱 - Dev (cafe-owner-dev) Firebase 인증서 파일 경로
owner_firebase_cred_path = os.getenv(
    "OWNER_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "cafe-owner-dev-firebase-adminsdk-fbsvc-dffff6ae75.json")
)

# Dev 앱 Firebase 인증서 파일 경로
dev_firebase_cred_path = os.getenv(
    "DEV_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "gifnut-dev-firebase-adminsdk-fbsvc-b834ddfd38.json")
)

print("initialize firebase")

# 앱 객체를 모듈 변수로 관리 (fcm_service에서 app= 파라미터로 사용)
user_app = None
owner_app = None
dev_app = None

# 사용자 앱 초기화
if "user_app" not in firebase_admin._apps:
    user_cred = credentials.Certificate(user_firebase_cred_path)
    user_app = firebase_admin.initialize_app(user_cred, name="user_app")
    print(f"✅ User App Firebase initialized: {user_firebase_cred_path}")
else:
    user_app = firebase_admin.get_app("user_app")

# 사장님 앱 Firebase 초기화 (cafe-owner-dev)
try:
    if "owner_app" not in firebase_admin._apps:
        owner_cred = credentials.Certificate(owner_firebase_cred_path)
        owner_app = firebase_admin.initialize_app(owner_cred, name="owner_app")
        print(f"✅ Owner App Firebase initialized: {owner_firebase_cred_path}")
    else:
        owner_app = firebase_admin.get_app("owner_app")
        print("⚠️  Owner App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  Owner App Firebase credentials not found: {owner_firebase_cred_path}")
except Exception as e:
    print(f"⚠️  Owner App Firebase initialization failed: {str(e)}")

# Dev 앱 Firebase 초기화
try:
    if "dev_app" not in firebase_admin._apps:
        dev_cred = credentials.Certificate(dev_firebase_cred_path)
        dev_app = firebase_admin.initialize_app(dev_cred, name="dev_app")
        print(f"✅ Dev App Firebase initialized: {dev_firebase_cred_path}")
    else:
        dev_app = firebase_admin.get_app("dev_app")
        print("⚠️  Dev App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  Dev App Firebase credentials not found: {dev_firebase_cred_path}")
except Exception as e:
    print(f"⚠️  Dev App Firebase initialization failed: {str(e)}")
