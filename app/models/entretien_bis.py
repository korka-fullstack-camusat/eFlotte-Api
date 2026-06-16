from sqlalchemy import Column, Integer, String, Numeric, JSON
from ..database import Base


class EntretienBis(Base):
    """Suivi des entretiens BIS par palier kilométrique — feuille 'ENTRETIEN BIS'."""
    __tablename__ = "entretiens_vehicule_bis"

    id                     = Column(Integer, primary_key=True, index=True)
    rt                     = Column(String(100), nullable=True)
    statut                 = Column(String(150), nullable=True)
    modele                 = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), unique=True, index=True, nullable=False)
    kms_depart             = Column(Numeric(12, 2), nullable=True)
    notes                  = Column(String(255), nullable=True)
    # Clés = paliers km ("112500", "120000", ...) ; valeurs = km relevé au passage (ou null)
    paliers                = Column(JSON, nullable=False, default=dict)
    reste                  = Column(Numeric(12, 2), nullable=True)
