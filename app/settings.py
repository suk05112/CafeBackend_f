from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, ValidationError



class Settings(BaseSettings):
    db_host: str = Field(default="localhost")
    db_port: int = Field(default=5432)
    db_user: str = Field(default="postgres")
    db_password: str = Field(default="password")
    db_name: str = Field(default="cafe_db")
    debug: bool = Field(default=True)
    

    # ✅ Pydantic v2 방식: .env 자동 로드 + 누락 무시
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    

settings = Settings()
print(f"settings: db_host={settings.db_host}, db_user={settings.db_user}")
