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
    # Accepte DESTINATION ou MOTIF comme colonne
    has_motif       = "MOTIF" in df.columns
    has_destination = "DESTINATION" in df.columns
    required_base = ["DATE", "IMMA", "CHAUFFEUR", "DEMANDEUR", "TELEPHONE", "PROJET", "DATE DEPART", "DATE RETOUR", "COMMENTAIRES"]
    if not has_motif and not has_destination:
        required_base.append("DESTINATION")  # force l'erreur si aucun des deux
    missing = [c for c in required_base if c not in df.columns]
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

    def parse_time(v) -> datetime.time | None:
        if pd.isna(v):
            return None
        try:
            if isinstance(v, datetime.time):
                return v
            t = pd.to_datetime(str(v), format="%H:%M", errors="coerce")
            if pd.isna(t):
                t = pd.to_datetime(str(v), errors="coerce")
            return t.time() if not pd.isna(t) else None
        except Exception:
            return None

    existing_map = {
        (m.date, m.immatriculation, m.demandeur, m.motif or m.destination): m
        for m in db.query(MissionChauffeur).all()
    }

    for idx, row in df.iterrows():
        try:
            mission_date = parse_date(row["DATE"])
            immatriculation = clean_str(row["IMMA"])
            if mission_date is None or not immatriculation:
                continue

            motif_val = clean_str(row.get("MOTIF")) if has_motif else None
            dest_val  = clean_str(row.get("DESTINATION")) if has_destination else None

            values = dict(
                date=mission_date,
                immatriculation=immatriculation,
                chauffeur=clean_str(row["CHAUFFEUR"]),
                demandeur=clean_str(row["DEMANDEUR"]),
                telephone=clean_str(row["TELEPHONE"]),
                projet=clean_str(row["PROJET"]),
                motif=motif_val or dest_val,
                destination=dest_val,
                heure_debut=parse_time(row.get("HEURE DE DEBUT") or row.get("HEURE DEBUT") or row.get("H DEBUT")),
                heure_fin=parse_time(row.get("HEURE DE FIN") or row.get("HEURE FIN") or row.get("H FIN")),
                date_depart=parse_date(row["DATE DEPART"]),
                date_retour=parse_date(row["DATE RETOUR"]),
                commentaires=clean_str(row["COMMENTAIRES"]),
            )

            key = (mission_date, immatriculation, values["demandeur"], motif_val or dest_val)
            existing = existing_map.get(key)
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                new_m = MissionChauffeur(**values)
                db.add(new_m)
                existing_map[key] = new_m
                created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 3, "message": str(e)})

    db.commit()
    return ImportMissionsResult(created=created, updated=updated, errors=errors)
