# Main place to control configuration values
from pydantic_settings import BaseSettings, SettingsConfigDict

from typing import Literal

class Settings(BaseSettings):
    app_name: str = "Aido Backend"
    environment: str = "development"
    database_url: str = "postgresql://postgres:password@localhost:5432/aido"

    detector_backend: Literal["stub", "yolo"] = "stub"
    yolo_model: str = "yolo11n.pt"


    # Check for .env file variables
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
