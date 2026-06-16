import datetime
from pydantic import BaseModel


class SuiviDevisBase(BaseModel):
    descriptions: str | None = None
    numero_devis: str | None = None
    valeur_devis: float | None = None
    date: datetime.date | None = None
    montant: float | None = None
    sous_traitant: str | None = None
    matricule: str | None = None
    code_snc: str | None = None
    po_emis: str | None = None


class SuiviDevisCreate(SuiviDevisBase):
    pass


class SuiviDevisUpdate(SuiviDevisBase):
    pass


class SuiviDevisOut(SuiviDevisBase):
    id: int
    model_config = {"from_attributes": True}


class SuiviDevisPage(BaseModel):
    items: list[SuiviDevisOut]
    total: int


class FiltresDevis(BaseModel):
    descriptions: list[str]
    sous_traitants: list[str]
    po_emis: list[str]


class ImportDevisResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]
