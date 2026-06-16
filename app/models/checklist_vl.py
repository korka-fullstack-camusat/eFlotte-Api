from sqlalchemy import Column, Integer, String, JSON
from ..database import Base


class CheckListVL(Base):
    """Suivi des check-lists hebdomadaires VL — issu de la feuille 'SUIVI DES CHECK LISTS VL'."""
    __tablename__ = "checklists_vl"

    id                     = Column(Integer, primary_key=True, index=True)
    brand                  = Column(String(100), nullable=True)
    model                  = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), unique=True, index=True, nullable=False)
    label                  = Column(String(150), nullable=True)
    car_group              = Column(String(150), index=True, nullable=True)
    # Clés = "SEMAINE 01".."SEMAINE 52" ; valeurs = statut (OK, NON, PANNE, PANNE + VT, GSD, ACCIDENTEE, MT NON AFFECTEE) ou null
    semaines               = Column(JSON, nullable=False, default=dict)
