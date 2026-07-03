from datetime import date
from pydantic import BaseModel


class CarburantBase(BaseModel):
    matricule:       str
    quantite_totale: float | None = None
    montant_total:   float | None = None
    mt_ht:           float | None = None
    prix_unitaire:   float | None = None
    type_carburant:  str   | None = None
    distance_totale: float | None = None
    distance_gps:    float | None = None
    car_group:       str   | None = None
    dernier_plein:   date  | None = None
    driver_name:     str   | None = None
    nom_chauffeur:   str   | None = None
    code_projet:     str   | None = None
    num_carte:       str   | None = None


class CarburantOut(CarburantBase):
    id: int

    model_config = {"from_attributes": True}


class CarburantPage(BaseModel):
    items: list[CarburantOut]
    total: int


class CarburantStats(BaseModel):
    total_vehicules:   int
    total_litres:      float
    total_montant:     float
    total_distance:    float
    nb_gazoil:         int
    nb_essence:        int
    litres_gazoil:     float
    litres_essence:    float
    montant_gazoil:    float
    montant_essence:   float
    top_consommateurs: list[dict]
    top_couts:         list[dict]


class CarburantUpdate(BaseModel):
    quantite_totale: float | None = None
    montant_total:   float | None = None
    mt_ht:           float | None = None
    prix_unitaire:   float | None = None
    type_carburant:  str   | None = None
    distance_totale: float | None = None
    distance_gps:    float | None = None
    car_group:       str   | None = None
    dernier_plein:   date  | None = None
    driver_name:     str   | None = None
    nom_chauffeur:   str   | None = None
    code_projet:     str   | None = None
    num_carte:       str   | None = None


class ImportCarburantResult(BaseModel):
    created: int
    updated: int
    errors:  list[dict]
