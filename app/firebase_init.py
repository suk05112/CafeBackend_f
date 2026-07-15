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

# 사장님 앱 (Owner App) Firebase 인증서 파일 경로
owner_firebase_cred_path = os.getenv(
    "OWNER_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "cafe-owner-firebase-adminsdk-4pxe9-e44664feb1.json")
)

# 사장님 앱 - Dev (cafe-owner-dev) Firebase 인증서 파일 경로
owner_dev_firebase_cred_path = os.getenv(
    "OWNER_DEV_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "cafe-owner-dev-firebase-adminsdk-fbsvc-dffff6ae75.json")
)

# 유저 앱 - Dev (gifnut-dev) Firebase 인증서 파일 경로
user_dev_firebase_cred_path = os.getenv(
    "USER_DEV_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "gifnut-dev-firebase-adminsdk-fbsvc-38860a44e8.json")
)

# Manager 앱 Firebase 인증서 파일 경로
manager_firebase_cred_path = os.getenv(
    "MANAGER_FIREBASE_CRED_PATH",
    os.path.join(BASE_DIR, "gifnutmanager-firebase-adminsdk-fbsvc-90c9adac85.json")
)

print("initialize firebase")

# 앱 객체를 모듈 변수로 관리 (fcm_service에서 app= 파라미터로 사용)
user_app = None
owner_app = None
user_dev_app = None
owner_dev_app = None
manager_app = None

# 사용자 앱 초기화
if "user_app" not in firebase_admin._apps:
    user_cred = credentials.Certificate(user_firebase_cred_path)
    user_app = firebase_admin.initialize_app(user_cred, name="user_app")
    print(f"✅ User App Firebase initialized: {user_firebase_cred_path}")
else:
    user_app = firebase_admin.get_app("user_app")

# 사장님 앱 Firebase 초기화 (cafe-owner)
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

# 사장님 앱 - Dev Firebase 초기화 (cafe-owner-dev)
try:
    if "owner_dev_app" not in firebase_admin._apps:
        owner_dev_cred = credentials.Certificate(owner_dev_firebase_cred_path)
        owner_dev_app = firebase_admin.initialize_app(owner_dev_cred, name="owner_dev_app")
        print(f"✅ Owner Dev App Firebase initialized: {owner_dev_firebase_cred_path}")
    else:
        owner_dev_app = firebase_admin.get_app("owner_dev_app")
        print("⚠️  Owner Dev App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  Owner Dev App Firebase credentials not found: {owner_dev_firebase_cred_path}")
except Exception as e:
    print(f"⚠️  Owner Dev App Firebase initialization failed: {str(e)}")

# 유저 앱 - Dev Firebase 초기화 (gifnut-dev)
# 앱 이름은 기존 호출부(api/endpoints/user.py의 get_user_firebase_app)와의 호환을 위해 "dev_app" 유지
try:
    if "dev_app" not in firebase_admin._apps:
        user_dev_cred = credentials.Certificate(user_dev_firebase_cred_path)
        user_dev_app = firebase_admin.initialize_app(user_dev_cred, name="dev_app")
        print(f"✅ User Dev App Firebase initialized: {user_dev_firebase_cred_path}")
    else:
        user_dev_app = firebase_admin.get_app("dev_app")
        print("⚠️  User Dev App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  User Dev App Firebase credentials not found: {user_dev_firebase_cred_path}")
except Exception as e:
    print(f"⚠️  User Dev App Firebase initialization failed: {str(e)}")

# Manager 앱 Firebase 초기화
try:
    if "manager_app" not in firebase_admin._apps:
        manager_cred = credentials.Certificate(manager_firebase_cred_path)
        manager_app = firebase_admin.initialize_app(manager_cred, name="manager_app")
        print(f"✅ Manager App Firebase initialized: {manager_firebase_cred_path}")
    else:
        manager_app = firebase_admin.get_app("manager_app")
        print("⚠️  Manager App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  Manager App Firebase credentials not found: {manager_firebase_cred_path}")
except Exception as e:
    print(f"⚠️  Manager App Firebase initialization failed: {str(e)}")


def _is_dev_env() -> bool:
    return os.getenv("ENV", "dev") in ("dev", "development", "local")


def get_active_user_app():
    """서버 ENV에 맞는 유저앱 Firebase 인스턴스 반환 (dev 서버 -> user_dev_app, prod 서버 -> user_app)"""
    return user_dev_app if _is_dev_env() else user_app


def get_active_owner_app():
    """서버 ENV에 맞는 사장님앱 Firebase 인스턴스 반환 (dev 서버 -> owner_dev_app, prod 서버 -> owner_app)"""
    return owner_dev_app if _is_dev_env() else owner_app
