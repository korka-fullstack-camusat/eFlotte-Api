from sqlalchemy import Column, Integer, String, Date, Float
from ..database import Base


class Pneumatique(Base):
    """Suivi des pneumatiques — feuille 'PNEUMATIQUE'."""
    __tablename__ = "pneumatiques"

    id                = Column(Integer, primary_key=True, index=True)
    fournisseur       = Column(String(150), nullable=True, index=True)
    type_location     = Column(String(100), nullable=True)
    immatriculation   = Column(String(30), nullable=False, index=True)
    chauffeur         = Column(String(150), nullable=True)
    kilometrage       = Column(Float, nullable=True)
    nb_pneus          = Column(Integer, nullable=True)
    ref_pneu          = Column(String(200), nullable=True)
    etat              = Column(String(100), nullable=True)
    snc               = Column(String(100), nullable=True)
    zone_intervention = Column(String(150), nullable=True)
    date_prevue       = Column(Date, nullable=True)
    commentaire       = Column(String(500), nullable=True)
