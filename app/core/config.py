from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Drones-Autonomos API"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "postgresql://drone_user:drone_password@localhost:5432/drone_db"
    SECRET_KEY: str = "e82be09c8935b2cfb534620c9d5486b9184cc3e8e02fa1eb50f2858ce341cf58"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()