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
    os.path.join(BASE_DIR, "cafe-owner-firebase-adminsdk-4pxe9-e44664feb1.json")  # 새 프로젝트 인증서 파일
)

print("initialize firebase")

# 기본 앱 초기화 (기존 호환성 유지 - 사용자 앱)
if not firebase_admin._apps:
    user_cred = credentials.Certificate(user_firebase_cred_path)
    firebase_admin.initialize_app(user_cred, name="user_app")
    print(f"✅ User App Firebase initialized: {user_firebase_cred_path}")

# 사장님 앱 Firebase 초기화 (별도 앱으로)
try:
    # 이미 'owner_app'이 초기화되었는지 확인
    if not any(app.name == "owner_app" for app in firebase_admin._apps if hasattr(app, 'name')):
        owner_cred = credentials.Certificate(owner_firebase_cred_path)
        firebase_admin.initialize_app(owner_cred, name="owner_app")
        print(f"✅ Owner App Firebase initialized: {owner_firebase_cred_path}")
    else:
        print("⚠️  Owner App Firebase already initialized")
except FileNotFoundError:
    print(f"⚠️  Owner App Firebase credentials not found: {owner_firebase_cred_path}")
    print("   Owner App features will be disabled. Set OWNER_FIREBASE_CRED_PATH environment variable.")
except Exception as e:
    print(f"⚠️  Owner App Firebase initialization failed: {str(e)}")
    print("   Owner App features may be disabled.")
