from sqlalchemy import Column, Integer, String, Float, Date
from ..database import Base


class SuiviDevis(Base):
    """Suivi des devis — issu de la feuille 'SUIVI DES DEVIS'."""
    __tablename__ = "suivi_devis"

    id             = Column(Integer, primary_key=True, index=True)
    descriptions   = Column(String(100), index=True, nullable=True)
    numero_devis   = Column(String(150), nullable=True)
    valeur_devis   = Column(Float, nullable=True)
    date           = Column(Date, index=True, nullable=True)
    montant        = Column(Float, nullable=True)
    sous_traitant  = Column(String(255), index=True, nullable=True)
    matricule      = Column(String(255), nullable=True)
    code_snc       = Column(String(255), nullable=True)
    po_emis        = Column(String(100), index=True, nullable=True)
