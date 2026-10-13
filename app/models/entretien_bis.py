from sqlalchemy import UniqueConstraint, Column, Integer, String, Numeric, JSON
from ..database import Base
from ..annee import Annuel, colonne_annee


class EntretienBis(Annuel, Base):
    """Suivi des entretiens BIS par palier kilométrique — feuille 'ENTRETIEN BIS'."""
    __tablename__ = "entretiens_vehicule_bis"
    __table_args__ = (UniqueConstraint("plaque_immatriculation", "annee", name="uq_entretiens_bis_plaque_annee"),)

    id                     = Column(Integer, primary_key=True, index=True)
    annee = colonne_annee()   # année du fichier importé (voir app/annee.py)
    rt                     = Column(String(100), nullable=True)
    statut                 = Column(String(150), nullable=True)
    modele                 = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), index=True, nullable=False)
    kms_depart             = Column(Numeric(12, 2), nullable=True)
    notes                  = Column(String(255), nullable=True)
    # Clés = paliers km ("112500", "120000", ...) ; valeurs = km relevé au passage (ou null)
    paliers                = Column(JSON, nullable=False, default=dict)
    reste                  = Column(Numeric(12, 2), nullable=True)
