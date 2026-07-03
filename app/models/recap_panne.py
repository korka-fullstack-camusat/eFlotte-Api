from sqlalchemy import Column, Integer, String, JSON
from ..database import Base


class RecapPanneVehicule(Base):
    """Récap mensuel des statuts véhicules — feuille 'RECAP DES PANNES'."""
    __tablename__ = "recap_pannes_vehicules"

    id                     = Column(Integer, primary_key=True, index=True)
    brand                  = Column(String(100), nullable=True)
    model                  = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), unique=True, index=True, nullable=False)
    label                  = Column(String(200), nullable=True)
    fuel_type              = Column(String(50), nullable=True)
    car_group              = Column(String(300), nullable=True)
    # Clés = "YYYY-MM" ; valeurs = "En service" | "En maintenance" | "Immobilisé" | null
    statuts_mensuels       = Column(JSON, nullable=False, default=dict)
