from pydantic import BaseModel
from datetime import date


class SuiviSinistreBase(BaseModel):
    date_sinistre:         date | None = None
    date_declaration:      date | None = None
    type_location:         str | None = None
    matricule:             str | None = None
    nom_chauffeur:         str | None = None
    snc:                   str | None = None
    projet:                str | None = None
    circonstances:         str | None = None
    statut:                str | None = None
    montant_indemnite:     float | None = None
    date_reglement:        date | None = None
    observations:          str | None = None
    dossier_suivi_par:     str | None = None
    position_vehicule:     str | None = None
    suivi_dossier_interne: str | None = None
    lieu_immobilisation:   str | None = None
    documentation:         bool | None = None
    traiter:               bool | None = None


class SuiviSinistreCreate(SuiviSinistreBase):
    pass


class SuiviSinistreUpdate(SuiviSinistreBase):
    pass


class SuiviSinistreOut(SuiviSinistreBase):
    id: int
    model_config = {"from_attributes": True}
