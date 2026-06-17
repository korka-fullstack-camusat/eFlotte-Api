from sqlalchemy import Column, Integer, String, Date, Float, Boolean
from ..database import Base


class SuiviSinistre(Base):
    __tablename__ = "suivi_sinistres"

    id                    = Column(Integer, primary_key=True, index=True)
    date_sinistre         = Column(Date, nullable=True)
    date_declaration      = Column(Date, nullable=True)
    type_location         = Column(String(100), nullable=True, index=True)  # LCD/LLD/CAMUSAT/AUTORENT
    matricule             = Column(String(50), nullable=True, index=True)
    nom_chauffeur         = Column(String(200), nullable=True)
    snc                   = Column(String(100), nullable=True)
    projet                = Column(String(100), nullable=True)
    circonstances         = Column(String(100), nullable=True)  # INCIDENT / ACCIDENT
    statut                = Column(String(100), nullable=True, index=True)
    montant_indemnite     = Column(Float, nullable=True)
    date_reglement        = Column(Date, nullable=True)
    observations          = Column(String(500), nullable=True)
    dossier_suivi_par     = Column(String(200), nullable=True)
    position_vehicule     = Column(String(100), nullable=True)
    suivi_dossier_interne = Column(String(200), nullable=True)
    lieu_immobilisation   = Column(String(200), nullable=True)
    documentation         = Column(Boolean, nullable=True)
    traiter               = Column(Boolean, nullable=True)
