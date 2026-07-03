from sqlalchemy import Column, Integer, String, Float, Date, Text
from ..database import Base


class Carburant(Base):
    __tablename__ = "carburant"

    id              = Column(Integer, primary_key=True, index=True)
    matricule       = Column(String(50), nullable=False, index=True)
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
