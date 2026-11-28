import ipaddress
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    DATABASE_URL: str = "sqlite:///./data/sms_gateway_v3.db"
    MEDIA_DIR: str = "./data/media"

    # Pixel 6 Android SMS Gateway
    SMS_API_URL: str = "http://127.0.0.1:8080"
    SMS_API_LOGIN: str = ""
    SMS_API_PASS: str = ""
    SMS_DID: str = "+19296141937"

    # Session & HIPAA Security
    SESSION_COOKIE_NAME: str = "smsgw_session"
    SESSION_COOKIE_SECURE: bool = True
    CLINIC_TIMEZONE: str = "America/New_York"
    SESSION_DAILY_CUTOFF_TIME: str = "00:05"
    SESSION_IDLE_TIMEOUT_MINUTES: int = 0
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    MIN_PASSWORD_LENGTH: int = 12

    # Reverse Proxy
    TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"

    # Webhook Security
    WEBHOOK_VERIFY_SIGNATURE: bool = False
    WEBHOOK_SIGNING_KEY: str = ""
    WEBHOOK_ALLOWED_IPS: str = ""
    WEBHOOK_MAX_CLOCK_SKEW_SECONDS: int = 300

    # Maintenance & Real-Time
    RAW_WEBHOOK_RETENTION_DAYS: int = 30
    SSE_HEARTBEAT_SECONDS: int = 15
    LOG_LEVEL: str = "INFO"

    @property
    def media_path(self) -> Path:
        return Path(self.MEDIA_DIR)

    @property
    def trusted_proxy_list(self) -> List[str]:
        return [ip.strip() for ip in self.TRUSTED_PROXY_IPS.split(",") if ip.strip()]

    @property
    def webhook_allowed_networks(self) -> List[ipaddress._BaseNetwork]:
        nets: List[ipaddress._BaseNetwork] = []
        for entry in self.WEBHOOK_ALLOWED_IPS.split(","):
            raw = entry.strip()
            if not raw:
                continue
            try:
                nets.append(ipaddress.ip_network(raw, strict=False))
            except ValueError:
                continue
        return nets


settings = Settings()
