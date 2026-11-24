import re
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Drones-Autonomos API"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "postgresql://drone_user:drone_password@localhost:5432/drone_db"
    SECRET_KEY: str = Field(..., min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    MISSION_SCHEDULER_ENABLED: bool = False
    VIDEO_STREAM_URL: str = "/api/v1/video/live"
    VIDEO_STREAM_PROTOCOL: str = "MJPEG/WebSocket"
    VIDEO_STREAM_FPS: int = 15
    VIDEO_JPEG_QUALITY: int = 75

    @field_validator("API_V1_STR", "VIDEO_STREAM_URL", mode="before")
    @classmethod
    def clean_git_bash_path(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        cleaned = value.strip().replace("\\", "/")
        cleaned = re.sub(r"^/?[A-Za-z]:/Program Files/Git", "", cleaned, flags=re.IGNORECASE)
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        return cleaned

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
