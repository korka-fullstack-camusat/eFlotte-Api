from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from ..database import Base


class CoutFlotte(Base):
    """Coûts mensuels par véhicule — issu de la feuille 'DATA_FLOTTES' (format long)."""
    __tablename__ = "couts_flotte"
    __table_args__ = (
        UniqueConstraint("plaque_immatriculation", "mois", "type_cout", name="uq_cout_plaque_mois_type"),
    )

    id                     = Column(Integer, primary_key=True, index=True)
    type_location          = Column(String(100), nullable=True)
    fournisseur            = Column(String(150), nullable=True)
    type_vehicule          = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), index=True, nullable=False)
    mois                   = Column(Date, index=True, nullable=False)
    # Codes : ASS, CARBURANT, DISTANCE, ENT, LOCAT, PEA, REP, TOTAL
    type_cout              = Column(String(20), index=True, nullable=False)
    valeur                 = Column(Numeric(14, 2), nullable=False, default=0)
    created_at             = Column(DateTime(timezone=True), server_default=func.now())
    updated_at             = Column(DateTime(timezone=True), onupdate=func.now())
