import io
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.suivi_devis import SuiviDevis
from ..schemas.suivi_devis import (
    SuiviDevisOut, SuiviDevisCreate, SuiviDevisUpdate, SuiviDevisPage,
    FiltresDevis, ImportDevisResult,
)
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/suivi-devis", tags=["Flotte — Suivi des devis"])


@router.get("", response_model=SuiviDevisPage)
def list_devis(
    descriptions: str | None = Query(None),
    sous_traitant: str | None = Query(None),
    po_emis: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(SuiviDevis)
    if descriptions:
        q = q.filter(SuiviDevis.descriptions == descriptions)
    if sous_traitant:
        q = q.filter(SuiviDevis.sous_traitant == sous_traitant)
    if po_emis:
        q = q.filter(SuiviDevis.po_emis == po_emis)
    total = q.count()
    items = (
        q.order_by(SuiviDevis.date.desc().nullslast(), SuiviDevis.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return SuiviDevisPage(items=items, total=total)


@router.get("/filtres", response_model=FiltresDevis)
def filtres_devis(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    def distinct(col):
        return sorted(v for (v,) in db.query(col).distinct().all() if v)

    return FiltresDevis(
        descriptions=distinct(SuiviDevis.descriptions),
        sous_traitants=distinct(SuiviDevis.sous_traitant),
        po_emis=distinct(SuiviDevis.po_emis),
    )


@router.post("", response_model=SuiviDevisOut, status_code=201)
def create_devis(
    payload: SuiviDevisCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    devis = SuiviDevis(**payload.model_dump())
    db.add(devis)
    db.commit()
    db.refresh(devis)
    return devis


@router.patch("/{devis_id}", response_model=SuiviDevisOut)
def update_devis(
    devis_id: int,
    payload: SuiviDevisUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    devis = db.query(SuiviDevis).filter(SuiviDevis.id == devis_id).first()
    if not devis:
        raise HTTPException(404, "Devis introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(devis, key, value)
    db.commit()
    db.refresh(devis)
    return devis


@router.delete("/{devis_id}", status_code=204)
def delete_devis(
    devis_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    devis = db.query(SuiviDevis).filter(SuiviDevis.id == devis_id).first()
    if not devis:
        raise HTTPException(404, "Devis introuvable")
    db.delete(devis)
    db.commit()


@router.post("/import", response_model=ImportDevisResult)
async def import_devis(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet_name = next((s for s in xls.sheet_names if "SUIVI" in s.upper() and "DEVIS" in s.upper()), None)
    if not sheet_name:
        raise HTTPException(400, "Feuille 'SUIVI DES DEVIS' introuvable dans le fichier")

    # Lignes 1-4 = totaux/filtres, ligne 5 = en-têtes -> header=4
    df = xls.parse(sheet_name, header=4)
    df.columns = [" ".join(str(c).split()) for c in df.columns]

    required_cols = ["DESCRIPTIONS", "# N° DEVIS", "VALEUR DEVIS", "DATE", "MONTANT", "SOUS-TRAITANT/SUPPLIERS", "MATRICULE", "CODE SNC", "PO EMIS"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise HTTPException(400, f"Colonnes manquantes dans '{sheet_name}': {', '.join(missing)}")

    created = 0
    updated = 0
    errors = []

    def parse_date(v) -> date | None:
        if pd.isna(v):
            return None
        if isinstance(v, (pd.Timestamp, datetime)):
            return v.date()
        try:
            return pd.to_datetime(v, dayfirst=True).date()
        except Exception:
            return None

    def parse_float(v) -> float | None:
        if pd.isna(v):
            return None
        try:
            return float(v)
        except Exception:
            return None

    def clean_str(v) -> str | None:
        return None if pd.isna(v) else str(v).strip()

    existing_map = {
        (d.descriptions, d.numero_devis, d.matricule): d
        for d in db.query(SuiviDevis).all()
    }

    for idx, row in df.iterrows():
        try:
            descriptions = clean_str(row["DESCRIPTIONS"])
            if not descriptions:
                continue

            values = dict(
                descriptions=descriptions,
                numero_devis=clean_str(row["# N° DEVIS"]),
                valeur_devis=parse_float(row["VALEUR DEVIS"]),
                date=parse_date(row["DATE"]),
                montant=parse_float(row["MONTANT"]),
                sous_traitant=clean_str(row["SOUS-TRAITANT/SUPPLIERS"]),
                matricule=clean_str(row["MATRICULE"]),
                code_snc=clean_str(row["CODE SNC"]),
                po_emis=clean_str(row["PO EMIS"]),
            )

            key = (descriptions, values["numero_devis"], values["matricule"])
            existing = existing_map.get(key)
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                new_d = SuiviDevis(**values)
                db.add(new_d)
                existing_map[key] = new_d
                created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 6, "message": str(e)})

    db.commit()
    return ImportDevisResult(created=created, updated=updated, errors=errors)
