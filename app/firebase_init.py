import firebase_admin
from firebase_admin import credentials
import os

# Firebase 인증서 파일 경로 (Docker 컨테이너 내부 경로 또는 환경 변수)
firebase_cred_path = os.getenv(
    "FIREBASE_CRED_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "cafeplatform-firebase-adminsdk-oq7t0-930245c6eb.json")
)

cred = credentials.Certificate(firebase_cred_path)


print("initialize firebase")
# Firebase Admin 초기화 (앱이 이미 초기화되었는지 확인)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
