from pydantic import BaseModel


class EntretienBase(BaseModel):
    type_location: str | None = None
    fournisseur: str | None = None
    type_vehicule: str | None = None
    plaque_immatriculation: str
    nom_chauffeur: str | None = None
    paliers: dict[str, float | None] = {}
    reste: float | None = None


class EntretienCreate(EntretienBase):
    pass


class EntretienUpdate(BaseModel):
    type_location: str | None = None
    fournisseur: str | None = None
    type_vehicule: str | None = None
    plaque_immatriculation: str | None = None
    nom_chauffeur: str | None = None
    paliers: dict[str, float | None] | None = None
    reste: float | None = None


class EntretienOut(EntretienBase):
    id: int
    model_config = {"from_attributes": True}


class ImportEntretiensResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]
