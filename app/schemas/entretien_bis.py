from pydantic import BaseModel


class EntretienBisBase(BaseModel):
    rt: str | None = None
    statut: str | None = None
    modele: str | None = None
    plaque_immatriculation: str
    kms_depart: float | None = None
    notes: str | None = None
    paliers: dict[str, float | None] = {}
    reste: float | None = None


class EntretienBisCreate(EntretienBisBase):
    pass


class EntretienBisUpdate(BaseModel):
    rt: str | None = None
    statut: str | None = None
    modele: str | None = None
    plaque_immatriculation: str | None = None
    kms_depart: float | None = None
    notes: str | None = None
    paliers: dict[str, float | None] | None = None
    reste: float | None = None


class EntretienBisOut(EntretienBisBase):
    id: int
    model_config = {"from_attributes": True}


class ImportEntretienBisResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]
