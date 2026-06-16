from sqlalchemy import Column, Integer, String, Date, Float
from ..database import Base


class SuiviPanne(Base):
    """Suivi des pannes et indisponibilités — feuille 'SUIVI DES PANNE'."""
    __tablename__ = "suivi_pannes"

    id                   = Column(Integer, primary_key=True, index=True)
    date                 = Column(Date, nullable=True)
    immatriculation      = Column(String(30), nullable=False, index=True)
    nom                  = Column(String(150), nullable=True)
    garage               = Column(String(100), nullable=True)
    nature_panne         = Column(String(500), nullable=True)
    date_indisponibilite = Column(Date, nullable=True)
    projet               = Column(String(100), nullable=True)
    date_fin_reparation  = Column(Date, nullable=True)
    site                 = Column(String(150), nullable=True)
    immobilisation_jrs   = Column(Float, nullable=True)
    commentaire          = Column(String(500), nullable=True)
