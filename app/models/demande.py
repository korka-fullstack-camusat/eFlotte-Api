from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from ..database import Base

NATURES_DEMANDE = {"REMONTEE": "Remontée", "PANNE": "Panne", "VIDANGE": "Vidange"}
STATUTS_DEMANDE = {"NOUVELLE": "Nouvelle", "EN_COURS": "En cours", "TRAITEE": "Traitée"}


class DemandeVehicule(Base):
    """Demande envoyée par un chauffeur depuis l'app mobile : remontée, panne ou vidange."""
    __tablename__ = "demandes_vehicule"

    id              = Column(Integer, primary_key=True, index=True)
    # SET NULL : supprimer un compte ne supprime pas l'historique des demandes
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    nature          = Column(String(20), index=True, nullable=False)      # REMONTEE | PANNE | VIDANGE
    immatriculation = Column(String(30), index=True, nullable=False)
    kilometrage     = Column(Integer, nullable=False)
    position        = Column(String(255), nullable=False)
    technicien      = Column(String(150), nullable=False)
    description     = Column(Text, nullable=True)        # « Nature » : explication du chauffeur
    nom_chauffeur   = Column(String(150), nullable=False)
    telephone       = Column(String(20), nullable=True)
    statut          = Column(String(20), index=True, nullable=False, default="NOUVELLE")
    commentaire     = Column(Text, nullable=True)                         # réponse de la gestion de flotte
    traitee_par     = Column(String(150), nullable=True)
    email_alerte_at = Column(DateTime(timezone=True), nullable=True)      # alerte e-mail envoyée
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationChauffeur(Base):
    """Notification affichée dans l'app chauffeur (et sur le téléphone) : relance, suivi de demande…"""
    __tablename__ = "notifications_chauffeur"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    type       = Column(String(20), nullable=False)            # RELANCE | DEMANDE | INFO
    titre      = Column(String(150), nullable=False)
    message    = Column(Text, nullable=True)
    data       = Column(JSON, nullable=True)                   # ex. {"demande_id": 3}
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    lue_at     = Column(DateTime(timezone=True), nullable=True)


class PushToken(Base):
    """Jeton de notification push (Expo) d'un téléphone connecté avec un compte chauffeur."""
    __tablename__ = "push_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token      = Column(String(255), unique=True, nullable=False)
    platform   = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
