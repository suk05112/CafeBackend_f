from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import os


class Settings(BaseSettings):
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    db_user: str = Field(default="postgres")
    db_password: str = Field(default="password")
    db_name: str = Field(default="cafe_db")
    debug: bool = Field(default=False)
    
    # Apple Sign In 설정
    apple_client_id: str = Field(default="", description="Apple Client ID")
    apple_team_id: str = Field(default="", description="Apple Team ID")
    apple_key_id: str = Field(default="***REMOVED_APPLE_KEY_ID***", description="Apple Key ID")
    apple_private_key_line1: str = Field(default="", description="Apple Private Key Line 1")
    apple_private_key_line2: str = Field(default="", description="Apple Private Key Line 2")
    apple_private_key_line3: str = Field(default="", description="Apple Private Key Line 3")
    apple_private_key_line4: str = Field(default="", description="Apple Private Key Line 4")
    apple_private_key_line5: str = Field(default="", description="Apple Private Key Line 5")
    apple_private_key_line6: str = Field(default="", description="Apple Private Key Line 6")
    apple_redirect_uri: str = Field(default="", description="Apple Redirect URI")

    # Payletter 설정
    payletter_client_id: str = Field(default="", description="Payletter Client ID")
    payletter_payment_api_key: str = Field(default="", description="Payletter Payment API Key")
    payletter_api_host: str = Field(default="", description="Payletter API Host")
    payletter_callback_url: str = Field(default="", description="Payletter 서버사이드 콜백 URL")
    payletter_return_url: str = Field(default="", description="Payletter 결제 완료 후 리다이렉트 URL (앱 딥링크)")
    payletter_cancel_url: str = Field(default="", description="Payletter 결제 취소 후 리다이렉트 URL (앱 딥링크)")

    # Payletter 네이버페이 전용 설정
    payletter_naver_client_id: str = Field(default="", description="Payletter 네이버페이 Client ID")
    payletter_naver_payment_api_key: str = Field(default="", description="Payletter 네이버페이 Payment API Key")

    # AWS 설정
    aws_access_key_id: str = Field(default="", description="AWS Access Key ID")
    aws_secret_access_key: str = Field(default="", description="AWS Secret Access Key")

    # Manager API Key
    manager_api_key: str = Field(default="", description="Manager 대시보드 API Key")

    # 알리고 카카오 알림톡 설정
    aligo_api_key: str = Field(default="", description="알리고 API Key")
    aligo_user_id: str = Field(default="", description="알리고 사용자 ID")
    aligo_sender_key: str = Field(default="", description="알림톡 발신프로필 키")
    aligo_sender: str = Field(default="", description="발신자 전화번호")

    # 기프티콘 만료 설정
    gifticon_expiry_days: int = Field(default=365, description="기프티콘 유효기간 (일)")

    # 드림시큐리티 mobileOK 본인확인 설정
    mok_keyinfo_path: str = Field(default="docs/mobileOK/mok_keyInfo_dev.dat", description="mok_keyInfo.dat 파일 경로")
    mok_keyinfo_password: str = Field(default="", description="mok_keyInfo.dat 복호화 비밀번호")
    mok_result_url: str = Field(default="https://scert.mobile-ok.com/gui/service/v1/result/request", description="드림시큐리티 검증 서버 URL")
    mok_return_url: str = Field(default="", description="표준창 결과 수신 URL (https://... /owner/mok/return)")

    def get_apple_private_key(self) -> str:
        """
        .env 파일에서 여러 줄로 나눠진 Private Key를 합쳐서 반환
        각 줄 사이에 \n을 포함하여 원본 형식 유지
        """
        lines = [
            self.apple_private_key_line1,
            self.apple_private_key_line2,
            self.apple_private_key_line3,
            self.apple_private_key_line4,
            self.apple_private_key_line5,
            self.apple_private_key_line6,
        ]
        # 빈 줄 제거하고 \n으로 합치기
        return "\n".join(line for line in lines if line)
    
    # Pydantic v2 방식: .env 자동 로드 + 누락 무시
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )
    

# ENV 환경 변수에 따라 .env.dev, .env.prod, 또는 .env.local 파일 로드
env = os.getenv("ENV", "dev")
if env in ["local"]:
    env_file = ".env.local"
elif env in ["dev", "development"]:
    env_file = ".env.dev"
elif env in ["prod", "production"]:
    env_file = ".env.prod"
else:
    env_file = ".env"

# Settings 인스턴스 생성 시 env_file을 직접 전달
settings = Settings(_env_file=env_file)
print(f"settings: db_host={settings.db_host}, db_user={settings.db_user}, env_file={env_file}")
