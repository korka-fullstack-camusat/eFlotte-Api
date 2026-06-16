from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://flotte_user:FlottePass2025@localhost:5435/eflotte"
    secret_key: str = "changeme-secret-key-eflotte"

    class Config:
        env_file = ".env"


settings = Settings()
