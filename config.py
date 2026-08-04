from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SMS_API_URL: str
    SMS_API_LOGIN: str
    SMS_API_PASS: str
    SMS_DID: str
    DATABASE_URL: str
    SERVER_URL: str

    class Config:
        env_file = ".env"

settings = Settings()