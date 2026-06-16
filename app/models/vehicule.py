from sqlalchemy import Column, Integer, String, Numeric, DateTime
from sqlalchemy.sql import func
from ..database import Base


class Vehicule(Base):
    """Inventaire de la flotte — issu de la feuille 'FLOTTE GLOBALE' du tableau de bord."""
    __tablename__ = "vehicules"

    id                    = Column(Integer, primary_key=True, index=True)
    type_location         = Column(String(100), nullable=True)
    fournisseur           = Column(String(150), nullable=True)
    type_vehicule         = Column(String(100), nullable=True)
    plaque_immatriculation = Column(String(30), unique=True, index=True, nullable=False)
    n_chassis             = Column(String(50), nullable=True)
    modele                = Column(String(100), nullable=True)
    couleur               = Column(String(50), nullable=True)
    autocollant           = Column(String(50), nullable=True)
    grille                = Column(String(50), nullable=True)
    croche                = Column(String(50), nullable=True)
    extincteurs           = Column(String(50), nullable=True)
    trousse_secours       = Column(String(50), nullable=True)
    peage                 = Column(String(50), nullable=True)
    carte_carburant       = Column(String(50), nullable=True)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())
