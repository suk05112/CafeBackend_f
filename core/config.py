from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import os


class Settings(BaseSettings):
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    db_user: str = Field(default="postgres")
    db_password: str = Field(default="password")
    db_name: str = Field(default="cafe_db")
    debug: bool = Field(default=True)
    
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
