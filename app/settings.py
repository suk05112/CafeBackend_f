from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    debug: bool

    class Config:
        env_file = ".env"

settings = Settings()