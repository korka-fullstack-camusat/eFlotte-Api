from datetime import datetime
from pydantic import BaseModel


class VehiculeBase(BaseModel):
    type_location: str | None = None
    fournisseur: str | None = None
    type_vehicule: str | None = None
    plaque_immatriculation: str
    n_chassis: str | None = None
    modele: str | None = None
    couleur: str | None = None
    autocollant: str | None = None
    grille: str | None = None
    croche: str | None = None
    extincteurs: str | None = None
    trousse_secours: str | None = None
    peage: str | None = None
    carte_carburant: str | None = None


class VehiculeCreate(VehiculeBase):
    pass


class VehiculeUpdate(BaseModel):
    type_location: str | None = None
    fournisseur: str | None = None
    type_vehicule: str | None = None
    plaque_immatriculation: str | None = None
    n_chassis: str | None = None
    modele: str | None = None
    couleur: str | None = None
    autocollant: str | None = None
    grille: str | None = None
    croche: str | None = None
    extincteurs: str | None = None
    trousse_secours: str | None = None
    peage: str | None = None
    carte_carburant: str | None = None


class VehiculeOut(VehiculeBase):
    id: int
    created_at: datetime | None = None
    model_config = {"from_attributes": True}
