from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://flotte_user:FlottePass2025@localhost:5435/eflotte"
    secret_key: str = "changeme-secret-key-eflotte"

    # .env contient aussi les variables du docker-compose (POSTGRES_*, DB_PORT…)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
