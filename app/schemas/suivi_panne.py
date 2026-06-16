from datetime import date as DateType
from pydantic import BaseModel


class SuiviPanneBase(BaseModel):
    date: DateType | None = None
    immatriculation: str
    nom: str | None = None
    garage: str | None = None
    nature_panne: str | None = None
    date_indisponibilite: DateType | None = None
    projet: str | None = None
    date_fin_reparation: DateType | None = None
    site: str | None = None
    immobilisation_jrs: float | None = None
    commentaire: str | None = None


class SuiviPanneCreate(SuiviPanneBase):
    pass


class SuiviPanneUpdate(BaseModel):
    date: DateType | None = None
    immatriculation: str | None = None
    nom: str | None = None
    garage: str | None = None
    nature_panne: str | None = None
    date_indisponibilite: DateType | None = None
    projet: str | None = None
    date_fin_reparation: DateType | None = None
    site: str | None = None
    immobilisation_jrs: float | None = None
    commentaire: str | None = None


class SuiviPanneOut(SuiviPanneBase):
    id: int
    model_config = {"from_attributes": True}


class SuiviPannePage(BaseModel):
    items: list[SuiviPanneOut]
    total: int


class ImportSuiviPanneResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]


class FiltresSuiviPanne(BaseModel):
    projets: list[str]
    garages: list[str]
    sites: list[str]
    immatriculations: list[str]
