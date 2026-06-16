from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.user import User
from ..models.vehicule import Vehicule
from ..schemas.vehicule import VehiculeOut, VehiculeCreate, VehiculeUpdate
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/vehicules", tags=["Flotte — Véhicules"])


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
