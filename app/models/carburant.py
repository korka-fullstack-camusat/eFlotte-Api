import datetime
from sqlalchemy import Column, Integer, String, Float, Date, Text, Index
from ..database import Base

def _current_year() -> int:
    return datetime.date.today().year


class Carburant(Base):
    __tablename__ = "carburant"

    id              = Column(Integer, primary_key=True, index=True)
    matricule       = Column(String(50), nullable=False, index=True)
    mois            = Column(Integer, nullable=False, default=1, index=True)  # 1=Jan … 12=Déc
    annee           = Column(Integer, nullable=False, default=_current_year, index=True)
    quantite_totale = Column(Float)
    montant_total   = Column(Float)
    mt_ht           = Column(Float)
    prix_unitaire   = Column(Float)
    type_carburant  = Column(String(20))        # GAZOIL | ESSENCE
    distance_totale = Column(Float)
    distance_gps    = Column(Float)
    car_group       = Column(String(500))
    dernier_plein   = Column(Date)
    driver_name     = Column(String(500))
    nom_chauffeur   = Column(String(500))
    code_projet     = Column(Text)
    num_carte       = Column(String(200))
    conso_100       = Column(Float)          # Conso/100 recommandée
    vehicle_type    = Column(String(100))    # Vehicle Type (Light, Truck…)
    dist_recommandee = Column(Float)         # Distance recommandée CO2

    __table_args__ = (
        Index("ix_carburant_annee_mois", "annee", "mois"),
    )
