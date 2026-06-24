from datetime import datetime, date
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
    marque: str | None = None
    annee: int | None = None
    statut: str | None = None
    type_carburant: str | None = None
    chauffeur: str | None = None
    kilometrage: int | None = None
    dernier_service: date | None = None
    prochaine_vidange: date | None = None
    localisation: str | None = None


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
    marque: str | None = None
    annee: int | None = None
    statut: str | None = None
    type_carburant: str | None = None
    chauffeur: str | None = None
    kilometrage: int | None = None
    dernier_service: date | None = None
    prochaine_vidange: date | None = None
    localisation: str | None = None


class VehiculeOut(VehiculeBase):
    id: int
    created_at: datetime | None = None
    model_config = {"from_attributes": True}
