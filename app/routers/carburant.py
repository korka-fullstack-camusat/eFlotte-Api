import io
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models.carburant import Carburant
from ..models.user import User
from ..schemas.carburant import CarburantBase, CarburantOut, CarburantPage, CarburantStats, CarburantUpdate, ImportCarburantResult
from ..services.auth_service import get_current_user, require_editor
from ..services.carburant_excel import feuille_carburant, importer_carburant

router = APIRouter(prefix="/api/carburant", tags=["Carburant"])


# ── Filtres disponibles ────────────────────────────────────────────────────────

@router.get("/periodes")
def get_periodes(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Retourne la liste des (annee, mois) ayant au moins une ligne, du plus récent au plus ancien."""
    rows = (
        db.query(Carburant.annee, Carburant.mois)
        .distinct()
        .order_by(Carburant.annee.desc(), Carburant.mois.desc())
        .all()
    )
    return [{"annee": r.annee, "mois": r.mois} for r in rows]


@router.get("/filtres")
def get_filtres(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    def distinct(col):
        return sorted({v for (v,) in db.query(col).distinct().all() if v})

    return {
        "car_groups":      distinct(Carburant.car_group),
        "types_carburant": distinct(Carburant.type_carburant),
        "matricules":      distinct(Carburant.matricule),
        "codes_projet":    distinct(Carburant.code_projet),
    }


# ── Liste paginée ──────────────────────────────────────────────────────────────

@router.get("", response_model=CarburantPage)
def list_carburant(
    mois:           int | None = Query(None, ge=1, le=12),
    annee:          int | None = Query(None),
    matricule:      str | None = None,
    car_group:      str | None = None,
    type_carburant: str | None = None,
    code_projet:    str | None = None,
    search:         str | None = None,
    page:           int = Query(1, ge=1),
    page_size:      int = Query(20, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Carburant)

    if mois is not None:
        q = q.filter(Carburant.mois == mois)
    if annee is not None:
        q = q.filter(Carburant.annee == annee)
    if matricule:
        q = q.filter(Carburant.matricule == matricule)
    if car_group:
        q = q.filter(Carburant.car_group == car_group)
    if type_carburant:
        q = q.filter(func.upper(Carburant.type_carburant) == type_carburant.upper())
    if code_projet:
        q = q.filter(Carburant.code_projet == code_projet)
    if search:
        like = f"%{search}%"
        q = q.filter(
            Carburant.matricule.ilike(like) |
            Carburant.driver_name.ilike(like) |
            Carburant.nom_chauffeur.ilike(like) |
            Carburant.car_group.ilike(like)
        )

    total = q.count()
    items = (
        q.order_by(Carburant.montant_total.desc().nullslast())
         .offset((page - 1) * page_size)
         .limit(page_size)
         .all()
    )
    return CarburantPage(items=items, total=total)


# ── Statistiques ───────────────────────────────────────────────────────────────

@router.get("/stats", response_model=CarburantStats)
def stats_carburant(
    car_group:      str | None = None,
    type_carburant: str | None = None,
    matricule:      str | None = None,
    annee:          int | None = Query(None),
    mois:           int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Carburant)
    if car_group:
        q = q.filter(Carburant.car_group == car_group)
    if type_carburant:
        q = q.filter(func.upper(Carburant.type_carburant) == type_carburant.upper())
    if matricule:
        q = q.filter(func.upper(func.trim(Carburant.matricule)) == matricule.strip().upper())
    if mois is not None:
        q = q.filter(Carburant.mois == mois)
    if annee is not None:
        q = q.filter(Carburant.annee == annee)

    rows = q.all()

    total_litres   = sum(r.quantite_totale or 0 for r in rows)
    total_montant  = sum(r.montant_total   or 0 for r in rows)
    total_distance = sum(r.distance_totale or 0 for r in rows)

    gazoil  = [r for r in rows if (r.type_carburant or "").upper() == "GAZOIL"]
    essence = [r for r in rows if (r.type_carburant or "").upper() == "ESSENCE"]

    # Top 10 consommateurs (litres)
    sorted_litres = sorted(rows, key=lambda r: r.quantite_totale or 0, reverse=True)[:10]
    top_consommateurs = [
        {
            "matricule":       r.matricule,
            "type_carburant":  r.type_carburant,
            "quantite_totale": r.quantite_totale,
            "car_group":       r.car_group,
        }
        for r in sorted_litres
    ]

    # Top 10 coûts (montant)
    sorted_montant = sorted(rows, key=lambda r: r.montant_total or 0, reverse=True)[:10]
    top_couts = [
        {
            "matricule":    r.matricule,
            "type_carburant": r.type_carburant,
            "montant_total": r.montant_total,
            "car_group":    r.car_group,
        }
        for r in sorted_montant
    ]

    return CarburantStats(
        # Un véhicule peut avoir une ligne GAZOIL et une ligne ESSENCE : on compte les matricules
        total_vehicules=len({r.matricule for r in rows}),
        total_litres=round(total_litres, 2),
        total_montant=round(total_montant, 2),
        total_montant_ht=round(sum(r.mt_ht or 0 for r in rows), 2),
        total_distance=round(total_distance, 2),
        nb_gazoil=len({r.matricule for r in gazoil}),
        nb_essence=len({r.matricule for r in essence}),
        litres_gazoil=round(sum(r.quantite_totale or 0 for r in gazoil), 2),
        litres_essence=round(sum(r.quantite_totale or 0 for r in essence), 2),
        montant_gazoil=round(sum(r.montant_total or 0 for r in gazoil), 2),
        montant_essence=round(sum(r.montant_total or 0 for r in essence), 2),
        top_consommateurs=top_consommateurs,
        top_couts=top_couts,
    )


# ── Création manuelle ─────────────────────────────────────────────────────────

@router.post("", response_model=CarburantOut)
def create_carburant(
    payload: CarburantBase,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    existing = db.query(Carburant).filter(
        Carburant.matricule == payload.matricule,
        Carburant.mois == payload.mois,
        Carburant.annee == payload.annee,
    ).first()
    if existing:
        raise HTTPException(409, "Une entrée existe déjà pour ce matricule, ce mois et cette année.")
    item = Carburant(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# ── Mise à jour partielle ──────────────────────────────────────────────────────

@router.patch("/{item_id}", response_model=CarburantOut)
def update_carburant(
    item_id: int,
    payload: CarburantUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    item = db.get(Carburant, item_id)
    if not item:
        raise HTTPException(404, "Enregistrement introuvable")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


# ── Import Excel ───────────────────────────────────────────────────────────────

import datetime as _dt

@router.post("/import", response_model=ImportCarburantResult)
async def import_carburant(
    file: UploadFile = File(...),
    annee: int = Query(_dt.date.today().year, ge=2015, le=2100, description="Année du fichier (fichier annuel)"),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    """Fichier annuel (tableau de bord flotte ou export carburant) : toute l'année
    choisie est remplacée, le mois de chaque ligne est lu dans le fichier."""
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    # Feuille CARBURANT, sinon première feuille (export carburant seul)
    res = importer_carburant(db, xls, annee, feuille_carburant(xls) or xls.sheet_names[0])
    if not res["mois"]:
        detail = res["errors"][0]["message"] if res["errors"] else "aucune ligne exploitable"
        if res["hors_annee"]:
            detail = f"les {res['hors_annee']} ligne(s) du fichier sont d'une autre année"
        raise HTTPException(400, f"Rien n'a été modifié pour {annee} : {detail}")
    db.commit()
    return ImportCarburantResult(
        created=res["created"], updated=res["updated"], errors=res["errors"],
        mois_detecte=res["mois"][-1], annee_detecte=annee,
        mois_importes=res["mois"], hors_annee=res["hors_annee"],
    )
