import firebase_admin
from firebase_admin import credentials

cred = credentials.Certificate("/home/ubuntu/CafeBackend/cafeplatform-firebase-adminsdk-oq7t0-930245c6eb.json")


print("initialize firebase")
# Firebase Admin 초기화 (앱이 이미 초기화되었는지 확인)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
