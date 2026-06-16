from datetime import date
from pydantic import BaseModel


class CoutFlotteOut(BaseModel):
    id: int
    type_location: str | None = None
    fournisseur: str | None = None
    type_vehicule: str | None = None
    plaque_immatriculation: str
    mois: date
    type_cout: str
    valeur: float
    model_config = {"from_attributes": True}


class CoutFlotteCreate(BaseModel):
    type_location: str | None = None
    fournisseur: str | None = None
    type_vehicule: str | None = None
    plaque_immatriculation: str
    mois: date
    type_cout: str
    valeur: float = 0


class CoutFlotteUpdate(BaseModel):
    type_location: str | None = None
    fournisseur: str | None = None
    type_vehicule: str | None = None
    plaque_immatriculation: str | None = None
    mois: date | None = None
    type_cout: str | None = None
    valeur: float | None = None


class CoutFlottePage(BaseModel):
    items: list[CoutFlotteOut]
    total: int


class ImportError_(BaseModel):
    ligne: int
    message: str


class ImportCoutsResult(BaseModel):
    created: int
    updated: int
    errors: list[ImportError_]


class KpiCouts(BaseModel):
    cout_total: float
    cout_carburant: float
    cout_distance: float
    cout_par_km: float


class EvolutionPoint(BaseModel):
    mois: int
    annee: int
    total: float


class RepartitionPoint(BaseModel):
    type_cout: str
    total: float


class VehiculeCoutPoint(BaseModel):
    plaque_immatriculation: str
    fournisseur: str | None = None
    type_vehicule: str | None = None
    total: float


class FiltresCouts(BaseModel):
    mois: list[date]
    plaques: list[str]
    types_vehicule: list[str]
    fournisseurs: list[str]
    types_location: list[str]


class PivotPoint(BaseModel):
    label: str
    total: float


class PivotResult(BaseModel):
    items: list[PivotPoint]
    total: float
