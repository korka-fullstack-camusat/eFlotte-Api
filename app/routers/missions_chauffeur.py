import io
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.mission_chauffeur import MissionChauffeur
from ..schemas.mission_chauffeur import (
    MissionChauffeurOut, MissionChauffeurCreate, MissionChauffeurUpdate, MissionChauffeurPage,
    FiltresMissions, ImportMissionsResult,
)
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/missions-chauffeur", tags=["Flotte — Chauffeurs Pôles"])


@router.get("", response_model=MissionChauffeurPage)
def list_missions(
    immatriculation: str | None = Query(None),
    chauffeur: str | None = Query(None),
    projet: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(MissionChauffeur)
    if immatriculation:
        q = q.filter(MissionChauffeur.immatriculation == immatriculation)
    if chauffeur:
        q = q.filter(MissionChauffeur.chauffeur == chauffeur)
    if projet:
        q = q.filter(MissionChauffeur.projet == projet)
    total = q.count()
    items = (
        q.order_by(MissionChauffeur.date.desc(), MissionChauffeur.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return MissionChauffeurPage(items=items, total=total)


@router.get("/filtres", response_model=FiltresMissions)
def filtres_missions(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    def distinct(col):
        return sorted(v for (v,) in db.query(col).distinct().all() if v)

    return FiltresMissions(
        immatriculations=distinct(MissionChauffeur.immatriculation),
        chauffeurs=distinct(MissionChauffeur.chauffeur),
        projets=distinct(MissionChauffeur.projet),
    )


@router.post("", response_model=MissionChauffeurOut, status_code=201)
def create_mission(
    payload: MissionChauffeurCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    mission = MissionChauffeur(**payload.model_dump())
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return mission


@router.patch("/{mission_id}", response_model=MissionChauffeurOut)
def update_mission(
    mission_id: int,
    payload: MissionChauffeurUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    mission = db.query(MissionChauffeur).filter(MissionChauffeur.id == mission_id).first()
    if not mission:
        raise HTTPException(404, "Mission introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(mission, key, value)
    db.commit()
    db.refresh(mission)
    return mission


@router.delete("/{mission_id}", status_code=204)
def delete_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    mission = db.query(MissionChauffeur).filter(MissionChauffeur.id == mission_id).first()
    if not mission:
        raise HTTPException(404, "Mission introuvable")
    db.delete(mission)
    db.commit()


@router.post("/import", response_model=ImportMissionsResult)
async def import_missions(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet_name = next((s for s in xls.sheet_names if "CHAUFFEUR" in s.upper() and "POLE" in s.upper()), None)
    if not sheet_name:
        raise HTTPException(400, "Feuille 'CHAUFFEUR POLES' introuvable dans le fichier")

    # Ligne 1 = titre ("ANNEE 2026"), ligne 2 = en-têtes -> header=1
    df = xls.parse(sheet_name, header=1)
    df.columns = [str(c).strip() for c in df.columns]
    required_cols = ["DATE", "IMMA", "CHAUFFEUR", "DEMANDEUR", "TELEPHONE", "PROJET", "DESTINATION", "DATE DEPART", "DATE RETOUR", "COMMENTAIRES"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise HTTPException(400, f"Colonnes manquantes dans '{sheet_name}': {', '.join(missing)}")

    created = 0
    updated = 0
    errors = []

    def parse_date(v) -> date | None:
        if pd.isna(v) or not isinstance(v, (pd.Timestamp, datetime)):
            return None
        return pd.to_datetime(v).date()

    def clean_str(v) -> str | None:
        return None if pd.isna(v) else str(v).strip()

    for idx, row in df.iterrows():
        try:
            mission_date = parse_date(row["DATE"])
            immatriculation = clean_str(row["IMMA"])
            if mission_date is None or not immatriculation:
                # ligne de séparation (ex: "MOIS D AVRIL 2026") ou ligne vide
                continue

            values = dict(
                date=mission_date,
                immatriculation=immatriculation,
                chauffeur=clean_str(row["CHAUFFEUR"]),
                demandeur=clean_str(row["DEMANDEUR"]),
                telephone=clean_str(row["TELEPHONE"]),
                projet=clean_str(row["PROJET"]),
                destination=clean_str(row["DESTINATION"]),
                date_depart=parse_date(row["DATE DEPART"]),
                date_retour=parse_date(row["DATE RETOUR"]),
                commentaires=clean_str(row["COMMENTAIRES"]),
            )

            existing = (
                db.query(MissionChauffeur)
                .filter_by(
                    date=mission_date,
                    immatriculation=immatriculation,
                    demandeur=values["demandeur"],
                    destination=values["destination"],
                )
                .first()
            )
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(MissionChauffeur(**values))
                created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 3, "message": str(e)})

    db.commit()
    return ImportMissionsResult(created=created, updated=updated, errors=errors)
