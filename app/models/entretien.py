from sqlalchemy import UniqueConstraint, Column, Integer, String, Numeric, JSON
from ..database import Base
from ..annee import Annuel, colonne_annee


class EntretienVehicule(Annuel, Base):
    """Suivi des entretiens par palier kilométrique — issu de la feuille 'ENTRTIENS'."""
    __tablename__ = "entretiens_vehicule"
    __table_args__ = (UniqueConstraint("plaque_immatriculation", "annee", name="uq_entretiens_vehicule_plaque_annee"),)

    id                     = Column(Integer, primary_key=True, index=True)
    annee = colonne_annee()   # année du fichier importé (voir app/annee.py)
    type_location          = Column(String(100), nullable=True)
    fournisseur            = Column(String(150), nullable=True)
    type_vehicule          = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), index=True, nullable=False)
    nom_chauffeur          = Column(String(150), nullable=True)
    # Clés = paliers km ("7500", "15000", ...) ; valeurs = km relevé au passage en atelier (ou null)
    paliers                = Column(JSON, nullable=False, default=dict)
    reste                  = Column(Numeric(12, 2), nullable=True)
