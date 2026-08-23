import datetime
from pydantic import BaseModel


class MissionChauffeurBase(BaseModel):
    date: datetime.date
    immatriculation: str
    chauffeur: str | None = None
    demandeur: str | None = None
    telephone: str | None = None
    projet: str | None = None
    motif: str | None = None
    destination: str | None = None  # conservé pour rétrocompatibilité import
    heure_debut: datetime.time | None = None
    heure_fin: datetime.time | None = None
    date_depart: datetime.date | None = None
    date_retour: datetime.date | None = None
    commentaires: str | None = None


class MissionChauffeurCreate(MissionChauffeurBase):
    pass


class MissionChauffeurUpdate(BaseModel):
    date: datetime.date | None = None
    immatriculation: str | None = None
    chauffeur: str | None = None
    demandeur: str | None = None
    telephone: str | None = None
    projet: str | None = None
    motif: str | None = None
    destination: str | None = None
    heure_debut: datetime.time | None = None
    heure_fin: datetime.time | None = None
    date_depart: datetime.date | None = None
    date_retour: datetime.date | None = None
    commentaires: str | None = None


class MissionChauffeurOut(MissionChauffeurBase):
    id: int
    model_config = {"from_attributes": True}


class MissionChauffeurPage(BaseModel):
    items: list[MissionChauffeurOut]
    total: int


class FiltresMissions(BaseModel):
    immatriculations: list[str]
    chauffeurs: list[str]
    projets: list[str]


class ImportMissionsResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]
