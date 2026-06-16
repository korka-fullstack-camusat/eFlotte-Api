from datetime import date as DateType
from pydantic import BaseModel


class PneumatiqueBase(BaseModel):
    fournisseur: str | None = None
    type_location: str | None = None
    immatriculation: str
    chauffeur: str | None = None
    kilometrage: float | None = None
    nb_pneus: int | None = None
    ref_pneu: str | None = None
    etat: str | None = None
    snc: str | None = None
    zone_intervention: str | None = None
    date_prevue: DateType | None = None
    commentaire: str | None = None


class PneumatiqueCreate(PneumatiqueBase):
    pass


class PneumatiqueUpdate(BaseModel):
    fournisseur: str | None = None
    type_location: str | None = None
    immatriculation: str | None = None
    chauffeur: str | None = None
    kilometrage: float | None = None
    nb_pneus: int | None = None
    ref_pneu: str | None = None
    etat: str | None = None
    snc: str | None = None
    zone_intervention: str | None = None
    date_prevue: DateType | None = None
    commentaire: str | None = None


class PneumatiqueOut(PneumatiqueBase):
    id: int
    model_config = {"from_attributes": True}


class PneumatiquePage(BaseModel):
    items: list[PneumatiqueOut]
    total: int


class ImportPneumatiqueResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]


class FiltresPneumatiques(BaseModel):
    fournisseurs: list[str]
    immatriculations: list[str]
    etats: list[str]
    sncs: list[str]
