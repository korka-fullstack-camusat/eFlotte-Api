from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://flotte_user:FlottePass2025@localhost:5435/eflotte"
    secret_key: str = "changeme-secret-key-eflotte"

    # Comptes chauffeurs importés en masse : mot de passe initial, à changer à la 1re connexion
    chauffeur_mot_de_passe_initial: str = "Camusat@2026"
    # Adresse de la plateforme envoyée dans le SMS (ex : http://16.171.169.105)
    app_url: str = ""

    # Orange SMS API (developer.orange.com) — SMS désactivés tant que client_id est vide
    orange_client_id: str = ""
    orange_client_secret: str = ""
    orange_sender_address: str = "tel:+2210000"   # numéro d'envoi fourni par Orange
    orange_sender_name: str = ""                  # nom d'expéditeur, s'il est validé par Orange

    # .env contient aussi les variables du docker-compose (POSTGRES_*, DB_PORT…)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
