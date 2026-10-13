from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://flotte_user:FlottePass2025@localhost:5435/eflotte"
    secret_key: str = "changeme-secret-key-eflotte"

    # Comptes chauffeurs importés en masse : mot de passe initial, à changer à la 1re connexion
    chauffeur_mot_de_passe_initial: str = "Camusat@2026"
    # Adresse de la plateforme envoyée dans le SMS (ex : http://16.171.169.105)
    app_url: str = ""

    # Orange SMS Pro Sénégal — SMS désactivés tant que login / token / clé sont vides.
    # Valeurs à mettre dans le .env du serveur uniquement.
    orange_sms_login: str = ""
    orange_sms_token: str = ""
    orange_sms_access_key: str = ""
    orange_sms_signature: str = "CAMUSAT NOC"     # nom d'expéditeur affiché sur le téléphone
    orange_sms_base_url: str = "https://api.orangesmspro.sn:8443/api/json"
    orange_sms_verify_ssl: bool = True

    # .env contient aussi les variables du docker-compose (POSTGRES_*, DB_PORT…)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
