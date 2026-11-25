import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models.user import User
from ..models.vehicule import Vehicule
from ..schemas.vehicule import VehiculeOut, VehiculeCreate, VehiculeUpdate
from ..services.auth_service import get_current_user, require_admin, require_editor
from ..services.import_vehicules import FichierInvalide, ajouter_manquants, lire_excel

router = APIRouter(prefix="/api/vehicules", tags=["Flotte — Véhicules"])


def _norm(val: str | None) -> str:
    """Normalise un statut en casse flexible → EN_SERVICE / EN_MAINTENANCE / IMMOBILISE."""
    import unicodedata
    if not val:
        return ""
    s = unicodedata.normalize("NFD", val.strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper().replace(" ", "_").replace("-", "_")


@router.get("/stats")
def stats_vehicules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    all_vehicules = db.query(Vehicule).all()
    total = len(all_vehicules)

    en_service = sum(1 for v in all_vehicules if _norm(v.statut) == "EN_SERVICE")
    en_maintenance = sum(1 for v in all_vehicules if _norm(v.statut) == "EN_MAINTENANCE")
    immobilises = sum(1 for v in all_vehicules if _norm(v.statut).startswith("IMMOBILISE"))
    taux = round((en_service / total) * 100) if total > 0 else 0

    # Répartition par type de carburant
    essence = sum(1 for v in all_vehicules if (v.type_carburant or "").upper() in ("ESSENCE",))
    gasoil  = sum(1 for v in all_vehicules if (v.type_carburant or "").upper() in ("GASOIL", "GAZOIL"))

    return {
        "total": total,
        "en_service": en_service,
        "en_maintenance": en_maintenance,
        "immobilises": immobilises,
        "taux_disponibilite": taux,
        "essence": essence,
        "gasoil": gasoil,
    }


@router.get("", response_model=list[VehiculeOut])
def list_vehicules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Vehicule).order_by(Vehicule.plaque_immatriculation).all()


@router.post("", response_model=VehiculeOut, status_code=201)
def create_vehicule(
    data: VehiculeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    if db.query(Vehicule).filter(Vehicule.plaque_immatriculation == data.plaque_immatriculation).first():
        raise HTTPException(400, "Un véhicule avec cette plaque existe déjà")
    vehicule = Vehicule(**data.model_dump())
    db.add(vehicule); db.commit(); db.refresh(vehicule)
    return vehicule


@router.post("/import-manquants")
async def importer_manquants(
    file: UploadFile = File(...),
    appliquer: bool = Form(False),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Export Excel des véhicules : liste (puis ajoute, si appliquer) les plaques absentes de la base.
    Les véhicules existants ne sont jamais modifiés ni supprimés."""
    try:
        lignes = lire_excel(io.BytesIO(await file.read()))
    except FichierInvalide as e:
        raise HTTPException(400, str(e))
    return ajouter_manquants(db, lignes, appliquer)


@router.patch("/{vehicule_id}", response_model=VehiculeOut)
def update_vehicule(
    vehicule_id: int,
    data: VehiculeUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    vehicule = db.query(Vehicule).filter(Vehicule.id == vehicule_id).first()
    if not vehicule:
        raise HTTPException(404, "Véhicule introuvable")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(vehicule, key, value)
    db.commit(); db.refresh(vehicule)
    return vehicule


@router.delete("/{vehicule_id}", status_code=204)
def delete_vehicule(
    vehicule_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    vehicule = db.query(Vehicule).filter(Vehicule.id == vehicule_id).first()
    if not vehicule:
        raise HTTPException(404, "Véhicule introuvable")
    db.delete(vehicule); db.commit()
