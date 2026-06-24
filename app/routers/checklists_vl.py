import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.checklist_vl import CheckListVL
from ..schemas.checklist_vl import (
    CheckListVLOut, CheckListVLCreate, CheckListVLUpdate, CheckListVLPage,
    FiltresCheckListVL, ImportCheckListVLResult,
)
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/checklists-vl", tags=["Flotte — Check-lists VL"])

NB_SEMAINES = 52
SEMAINES = [f"SEMAINE {i:02d}" for i in range(1, NB_SEMAINES + 1)]

STATUTS = ["OK", "NON", "PANNE", "PANNE + VT", "GSD", "ACCIDENTEE", "MT NON AFFECTEE"]


@router.get("/semaines", response_model=list[str])
def list_semaines(_: User = Depends(get_current_user)):
    return SEMAINES


@router.get("/statuts", response_model=list[str])
def list_statuts(_: User = Depends(get_current_user)):
    return STATUTS


@router.get("", response_model=CheckListVLPage)
def list_checklists(
    brand: str | None = Query(None),
    car_group: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(CheckListVL)
    if brand:
        q = q.filter(CheckListVL.brand == brand)
    if car_group:
        q = q.filter(CheckListVL.car_group == car_group)
    total = q.count()
    items = (
        q.order_by(CheckListVL.plaque_immatriculation)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return CheckListVLPage(items=items, total=total)


@router.get("/filtres", response_model=FiltresCheckListVL)
def filtres_checklists(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    def distinct(col):
        return sorted(v for (v,) in db.query(col).distinct().all() if v)

    return FiltresCheckListVL(
        brands=distinct(CheckListVL.brand),
        car_groups=distinct(CheckListVL.car_group),
    )


@router.post("", response_model=CheckListVLOut, status_code=201)
def create_checklist(
    payload: CheckListVLCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    if db.query(CheckListVL).filter(CheckListVL.plaque_immatriculation == payload.plaque_immatriculation).first():
        raise HTTPException(400, "Une check-list existe déjà pour cette plaque")
    checklist = CheckListVL(**payload.model_dump())
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist


@router.patch("/{checklist_id}", response_model=CheckListVLOut)
def update_checklist(
    checklist_id: int,
    payload: CheckListVLUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    checklist = db.query(CheckListVL).filter(CheckListVL.id == checklist_id).first()
    if not checklist:
        raise HTTPException(404, "Check-list introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(checklist, key, value)
    db.commit()
    db.refresh(checklist)
    return checklist


@router.delete("/{checklist_id}", status_code=204)
def delete_checklist(
    checklist_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    checklist = db.query(CheckListVL).filter(CheckListVL.id == checklist_id).first()
    if not checklist:
        raise HTTPException(404, "Check-list introuvable")
    db.delete(checklist)
    db.commit()


def normalize_statut(v) -> str | None:
    if pd.isna(v):
        return None
    s = " ".join(str(v).strip().upper().split())
    if s in ("OK",):
        return "OK"
    if s in ("NON",):
        return "NON"
    if s in ("PANNE",):
        return "PANNE"
    if s in ("PANNE + VT", "PANNE+VT"):
        return "PANNE + VT"
    if s in ("GSD",):
        return "GSD"
    if "ACCIDENT" in s:
        return "ACCIDENTEE"
    if s in ("MT NON AFFECTEE",):
        return "MT NON AFFECTEE"
    return s or None


@router.post("/import", response_model=ImportCheckListVLResult)
async def import_checklists(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet_name = next((s for s in xls.sheet_names if "CHECK" in s.upper() and "LIST" in s.upper()), None)
    if not sheet_name:
        raise HTTPException(400, "Feuille 'SUIVI DES CHECK LISTS VL' introuvable dans le fichier")

    # Ligne 1 = vide, ligne 2 = en-têtes -> header=1
    df = xls.parse(sheet_name, header=1)
    df.columns = [" ".join(str(c).split()) for c in df.columns]

    required_cols = ["Brand", "Model", "Reg. №", "Label", "Car Group"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise HTTPException(400, f"Colonnes manquantes dans '{sheet_name}': {', '.join(missing)}")

    created = 0
    updated = 0
    errors = []

    def clean_str(v) -> str | None:
        return None if pd.isna(v) else str(v).strip()

    seen_in_batch: dict[str, CheckListVL] = {c.plaque_immatriculation: c for c in db.query(CheckListVL).all()}
    touched: set[str] = set()

    for idx, row in df.iterrows():
        try:
            plaque = clean_str(row["Reg. №"])
            if not plaque:
                continue

            semaines = {}
            for sem in SEMAINES:
                semaines[sem] = normalize_statut(row[sem]) if sem in df.columns else None

            values = dict(
                brand=clean_str(row["Brand"]),
                model=clean_str(row["Model"]),
                label=clean_str(row["Label"]),
                car_group=clean_str(row["Car Group"]),
                semaines=semaines,
            )

            existing = seen_in_batch.get(plaque)
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                if plaque not in touched:
                    updated += 1
                seen_in_batch[plaque] = existing
            else:
                new_checklist = CheckListVL(plaque_immatriculation=plaque, **values)
                db.add(new_checklist)
                seen_in_batch[plaque] = new_checklist
                created += 1
            touched.add(plaque)
        except Exception as e:
            errors.append({"ligne": int(idx) + 3, "message": str(e)})

    db.commit()
    return ImportCheckListVLResult(created=created, updated=updated, errors=errors)
