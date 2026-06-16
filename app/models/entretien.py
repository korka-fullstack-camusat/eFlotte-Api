from sqlalchemy import Column, Integer, String, Numeric, JSON
from ..database import Base


class EntretienVehicule(Base):
    """Suivi des entretiens par palier kilométrique — issu de la feuille 'ENTRTIENS'."""
    __tablename__ = "entretiens_vehicule"

    id                     = Column(Integer, primary_key=True, index=True)
    type_location          = Column(String(100), nullable=True)
    fournisseur            = Column(String(150), nullable=True)
    type_vehicule          = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), unique=True, index=True, nullable=False)
    nom_chauffeur          = Column(String(150), nullable=True)
    # Clés = paliers km ("7500", "15000", ...) ; valeurs = km relevé au passage en atelier (ou null)
    paliers                = Column(JSON, nullable=False, default=dict)
    reste                  = Column(Numeric(12, 2), nullable=True)
