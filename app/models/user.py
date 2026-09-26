from sqlalchemy import Column, Integer, String, Boolean
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String, unique=True, index=True, nullable=False)
    full_name       = Column(String, nullable=True)
    email           = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active       = Column(Boolean, default=True)
    # Rôle : ADMIN (gestion complète + utilisateurs), EDITOR (lecture/écriture), HSE,
    # VIEWER (lecture seule), CHAUFFEUR (accès uniquement à l'app mobile de checklist)
    role            = Column(String(20), nullable=False, default="EDITOR")
    # Véhicule attribué (CHAUFFEUR) — plaque plutôt que clé étrangère pour survivre aux réimports de la flotte
    vehicule_plaque = Column(String(30), nullable=True)
