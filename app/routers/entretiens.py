import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.entretien import EntretienVehicule
from ..schemas.entretien import EntretienOut, EntretienCreate, EntretienUpdate, ImportEntretiensResult
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/entretiens", tags=["Flotte — Entretiens"])

# Paliers kilométriques fixes (feuille 'ENTRTIENS' : colonnes F à S)
PALIERS_KM = [7500, 15000, 22500, 30000, 37500, 45000, 52500, 60000, 67500, 75000, 82500, 90000, 97500, 105000]


@router.get("/paliers", response_model=list[int])
def list_paliers(_: User = Depends(get_current_user)):
    return PALIERS_KM


@router.get("", response_model=list[EntretienOut])
def list_entretiens(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(EntretienVehicule).order_by(EntretienVehicule.plaque_immatriculation).all()


@router.post("", response_model=EntretienOut, status_code=201)
def create_entretien(
    data: EntretienCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    if db.query(EntretienVehicule).filter(EntretienVehicule.plaque_immatriculation == data.plaque_immatriculation).first():
        raise HTTPException(400, "Un suivi d'entretien existe déjà pour cette plaque")
    entretien = EntretienVehicule(**data.model_dump())
    db.add(entretien); db.commit(); db.refresh(entretien)
    return entretien


@router.patch("/{entretien_id}", response_model=EntretienOut)
def update_entretien(
    entretien_id: int,
    data: EntretienUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    entretien = db.query(EntretienVehicule).filter(EntretienVehicule.id == entretien_id).first()
    if not entretien:
        raise HTTPException(404, "Suivi d'entretien introuvable")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entretien, key, value)
    db.commit(); db.refresh(entretien)
    return entretien


@router.delete("/{entretien_id}", status_code=204)
def delete_entretien(
    entretien_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    entretien = db.query(EntretienVehicule).filter(EntretienVehicule.id == entretien_id).first()
    if not entretien:
        raise HTTPException(404, "Suivi d'entretien introuvable")
    db.delete(entretien); db.commit()


@router.post("/import", response_model=ImportEntretiensResult)
async def import_entretiens(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet_name = next((s for s in xls.sheet_names if "ENTRTIEN" in s.upper().replace(" ", "")), None)
    if not sheet_name:
        raise HTTPException(400, "Feuille 'ENTRTIENS' introuvable dans le fichier")

    # Ligne 3 = en-têtes (Matricule, NOM, paliers..., REST) -> header=2
    df = xls.parse(sheet_name, header=2)
    cols = list(df.columns)
    if len(cols) < 5 + len(PALIERS_KM) + 1:
        raise HTTPException(400, f"Structure inattendue dans la feuille '{sheet_name}'")

    # Colonnes par position : A=type_location, B=fournisseur, C=type_vehicule, D=Matricule, E=NOM, F..S=paliers, T=REST
    col_type_location, col_fournisseur, col_type_vehicule, col_matricule, col_nom = cols[:5]
    col_paliers = cols[5:5 + len(PALIERS_KM)]
    col_reste = cols[5 + len(PALIERS_KM)]

    created = 0
    updated = 0
    errors = []

    existing_map = {e.plaque_immatriculation: e for e in db.query(EntretienVehicule).all()}

    for idx, row in df.iterrows():
        try:
            plaque = row[col_matricule]
            if pd.isna(plaque) or not str(plaque).strip():
                continue
            plaque = str(plaque).strip()

            def clean_str(v):
                return None if pd.isna(v) else str(v).strip()

            def clean_num(v):
                return None if pd.isna(v) else float(v)

            paliers = {}
            for km, col in zip(PALIERS_KM, col_paliers):
                paliers[str(km)] = clean_num(row[col])

            existing = existing_map.get(plaque)
            values = dict(
                type_location=clean_str(row[col_type_location]),
                fournisseur=clean_str(row[col_fournisseur]),
                type_vehicule=clean_str(row[col_type_vehicule]),
                nom_chauffeur=clean_str(row[col_nom]),
                paliers=paliers,
                reste=clean_num(row[col_reste]),
            )
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                new_e = EntretienVehicule(plaque_immatriculation=plaque, **values)
                db.add(new_e)
                existing_map[plaque] = new_e
                created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 4, "message": str(e)})

    db.commit()
    return ImportEntretiensResult(created=created, updated=updated, errors=errors)
