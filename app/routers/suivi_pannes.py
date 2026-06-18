import io
from datetime import date as DateType

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.suivi_panne import SuiviPanne
from ..schemas.suivi_panne import (
    SuiviPanneOut, SuiviPanneCreate, SuiviPanneUpdate,
    SuiviPannePage, ImportSuiviPanneResult, FiltresSuiviPanne,
)
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/suivi-pannes", tags=["Flotte — Suivi des Pannes"])


def _apply_filters(q, projet, garage, site, immatriculation, statut, search):
    if projet:
        q = q.filter(SuiviPanne.projet == projet)
    if garage:
        q = q.filter(SuiviPanne.garage == garage)
    if site:
        q = q.filter(SuiviPanne.site == site)
    if immatriculation:
        q = q.filter(SuiviPanne.immatriculation == immatriculation)
    if statut == "repare":
        q = q.filter(SuiviPanne.date_fin_reparation.isnot(None))
    elif statut == "en_cours":
        q = q.filter(SuiviPanne.date_fin_reparation.is_(None))
    if search:
        like = f"%{search}%"
        q = q.filter(
            SuiviPanne.immatriculation.ilike(like) |
            SuiviPanne.nom.ilike(like) |
            SuiviPanne.nature_panne.ilike(like) |
            SuiviPanne.projet.ilike(like) |
            SuiviPanne.site.ilike(like)
        )
    return q


@router.get("/filtres", response_model=FiltresSuiviPanne)
def get_filtres(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    def distinct(col):
        return sorted({v for (v,) in db.query(col).distinct().all() if v})
    return FiltresSuiviPanne(
        projets=distinct(SuiviPanne.projet),
        garages=distinct(SuiviPanne.garage),
        sites=distinct(SuiviPanne.site),
        immatriculations=distinct(SuiviPanne.immatriculation),
    )


@router.get("", response_model=SuiviPannePage)
def list_pannes(
    projet: str | None = None,
    garage: str | None = None,
    site: str | None = None,
    immatriculation: str | None = None,
    statut: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = _apply_filters(
        db.query(SuiviPanne),
        projet, garage, site, immatriculation, statut, search,
    )
    total = q.count()
    items = (
        q.order_by(SuiviPanne.date.desc().nullslast(), SuiviPanne.id.desc())
         .offset((page - 1) * page_size)
         .limit(page_size)
         .all()
    )
    return SuiviPannePage(items=items, total=total)


@router.post("", response_model=SuiviPanneOut, status_code=201)
def create_panne(
    data: SuiviPanneCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    p = SuiviPanne(**data.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.patch("/{panne_id}", response_model=SuiviPanneOut)
def update_panne(
    panne_id: int,
    data: SuiviPanneUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    p = db.query(SuiviPanne).filter(SuiviPanne.id == panne_id).first()
    if not p:
        raise HTTPException(404, "Panne introuvable")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return p


@router.delete("/{panne_id}", status_code=204)
def delete_panne(
    panne_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    p = db.query(SuiviPanne).filter(SuiviPanne.id == panne_id).first()
    if not p:
        raise HTTPException(404, "Panne introuvable")
    db.delete(p); db.commit()


@router.post("/import", response_model=ImportSuiviPanneResult)
async def import_pannes(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet_name = next(
        (s for s in xls.sheet_names if "PANNE" in s.upper()),
        None
    )
    if not sheet_name:
        raise HTTPException(400, "Feuille 'SUIVI DES PANNE' introuvable dans le fichier")

    # Ligne 1 = en-têtes (header=0)
    df = xls.parse(sheet_name, header=0)

    # Mapping flexible des colonnes (insensible casse + espaces)
    col_map = {}
    aliases = {
        "date":                  ["date"],
        "immatriculation":       ["imma", "immatriculation", "plaque"],
        "nom":                   ["nom"],
        "garage":                ["garage"],
        "nature_panne":          ["nature", "nature de non", "panne"],
        "date_indisponibilite":  ["date d'indisponibilit", "indisponib"],
        "projet":                ["projet"],
        "date_fin_reparation":   ["date de fin", "fin de réparation", "fin de reparation"],
        "site":                  ["site"],
        "immobilisation_jrs":    ["immobilisation", "immo", "jrs"],
        "commentaire":           ["commentaire", "observation"],
    }
    for col in df.columns:
        col_lower = str(col).lower().strip()
        for field, keys in aliases.items():
            if field not in col_map and any(k in col_lower for k in keys):
                col_map[field] = col

    if "immatriculation" not in col_map:
        raise HTTPException(400, "Colonne IMMA/Immatriculation introuvable dans la feuille")

    def clean_str(v) -> str | None:
        if pd.isna(v):
            return None
        s = str(v).strip()
        return s if s and s.upper() not in ("NAN", "N/A", "N//A", "NA") else None

    def clean_date(v) -> DateType | None:
        if pd.isna(v):
            return None
        try:
            return pd.to_datetime(v, dayfirst=True).date()
        except Exception:
            return None

    created = 0
    updated = 0
    errors = []

    for idx, row in df.iterrows():
        try:
            imma = clean_str(row.get(col_map.get("immatriculation")))
            if not imma:
                continue

            nature = clean_str(row.get(col_map.get("nature_panne"))) if "nature_panne" in col_map else None
            date_val = clean_date(row.get(col_map.get("date"))) if "date" in col_map else None
            date_indisp = clean_date(row.get(col_map.get("date_indisponibilite"))) if "date_indisponibilite" in col_map else None
            date_fin = clean_date(row.get(col_map.get("date_fin_reparation"))) if "date_fin_reparation" in col_map else None

            values = dict(
                date=date_val,
                immatriculation=imma,
                nom=clean_str(row.get(col_map.get("nom"))) if "nom" in col_map else None,
                garage=clean_str(row.get(col_map.get("garage"))) if "garage" in col_map else None,
                nature_panne=nature,
                date_indisponibilite=date_indisp,
                projet=clean_str(row.get(col_map.get("projet"))) if "projet" in col_map else None,
                date_fin_reparation=date_fin,
                site=clean_str(row.get(col_map.get("site"))) if "site" in col_map else None,
                immobilisation_jrs=float(row[col_map["immobilisation_jrs"]]) if "immobilisation_jrs" in col_map and not pd.isna(row.get(col_map["immobilisation_jrs"])) else None,
                commentaire=clean_str(row.get(col_map.get("commentaire"))) if "commentaire" in col_map else None,
            )

            # Pas de clé unique → toujours insérer (chaque ligne est un événement)
            db.add(SuiviPanne(**values))
            created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 2, "message": str(e)})

    db.commit()
    return ImportSuiviPanneResult(created=created, updated=updated, errors=errors)
