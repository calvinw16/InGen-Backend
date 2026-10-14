# Main place to control configuration values
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aido Backend"
    environment: str = "development"
    database_url: str = "postgresql://postgres:password@localhost:5432/aido"

    # Check for .env file variables
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
