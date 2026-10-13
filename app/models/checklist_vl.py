from sqlalchemy import UniqueConstraint, Column, Integer, String, JSON
from ..database import Base
from ..annee import Annuel, colonne_annee


class CheckListVL(Annuel, Base):
    """Suivi des check-lists hebdomadaires VL — issu de la feuille 'SUIVI DES CHECK LISTS VL'."""
    __tablename__ = "checklists_vl"
    __table_args__ = (UniqueConstraint("plaque_immatriculation", "annee", name="uq_checklists_vl_plaque_annee"),)

    id                     = Column(Integer, primary_key=True, index=True)
    annee = colonne_annee()   # année du fichier importé (voir app/annee.py)
    brand                  = Column(String(100), nullable=True)
    model                  = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), index=True, nullable=False)
    label                  = Column(String(150), nullable=True)
    car_group              = Column(String(150), index=True, nullable=True)
    # Clés = "SEMAINE 01".."SEMAINE 52" ; valeurs = statut (OK, NON, PANNE, PANNE + VT, GSD, ACCIDENTEE, MT NON AFFECTEE) ou null
    semaines               = Column(JSON, nullable=False, default=dict)
