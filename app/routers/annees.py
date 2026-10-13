import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from ..annee import annee_courante
from ..database import get_db
from ..models import (
    Carburant, CheckListVL, CoutFlotte, EntretienBis, EntretienVehicule,
    MissionChauffeur, Pneumatique, SuiviDevis, SuiviPanne, SuiviSinistre,
)
from ..models.user import User
from ..services.auth_service import get_current_user

router = APIRouter(prefix="/api/annees", tags=["Années"])

MODELES_ANNUELS = (
    Carburant, CheckListVL, CoutFlotte, EntretienBis, EntretienVehicule,
    MissionChauffeur, Pneumatique, SuiviDevis, SuiviPanne, SuiviSinistre,
)


@router.get("", response_model=list[int])
def annees_disponibles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Années ayant des données importées (+ l'année en cours), de la plus récente à la plus ancienne."""
    annee_courante.set(None)   # cette liste ne doit pas être filtrée par l'année consultée
    annees = {datetime.date.today().year}
    for modele in MODELES_ANNUELS:
        annees.update(a for (a,) in db.query(distinct(modele.annee)).all() if a)
    return sorted(annees, reverse=True)
