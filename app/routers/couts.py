import io
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.cout_flotte import CoutFlotte
from ..schemas.cout_flotte import (
    CoutFlotteOut, CoutFlotteCreate, CoutFlotteUpdate, CoutFlottePage, ImportCoutsResult, KpiCouts,
    EvolutionPoint, RepartitionPoint, VehiculeCoutPoint, FiltresCouts, PivotPoint, PivotResult,
)
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/couts", tags=["Coûts — Suivi global"])

TYPES_COUT_FCFA = ["ASS", "CARBURANT", "ENT", "LOCAT", "PEA", "REP"]

PIVOT_COLUMNS = {
    "plaque": CoutFlotte.plaque_immatriculation,
    "mois": CoutFlotte.mois,
    "type_vehicule": CoutFlotte.type_vehicule,
    "fournisseur": CoutFlotte.fournisseur,
    "type_location": CoutFlotte.type_location,
    "type_cout": CoutFlotte.type_cout,
}


def _apply_filters(
    q,
    annee: int | None = None,
    mois: date | None = None,
    plaque: str | None = None,
    type_vehicule: str | None = None,
    fournisseur: str | None = None,
    type_location: str | None = None,
):
    if mois:
        q = q.filter(CoutFlotte.mois == mois)
    elif annee:
        q = q.filter(extract("year", CoutFlotte.mois) == annee)
    if plaque:
        q = q.filter(CoutFlotte.plaque_immatriculation == plaque)
    if type_vehicule:
        q = q.filter(CoutFlotte.type_vehicule == type_vehicule)
    if fournisseur:
        q = q.filter(CoutFlotte.fournisseur == fournisseur)
    if type_location:
        q = q.filter(CoutFlotte.type_location == type_location)
    return q


@router.get("", response_model=CoutFlottePage)
def list_couts(
    annee: int | None = Query(None),
    mois: date | None = Query(None),
    plaque: str | None = Query(None),
    type_vehicule: str | None = Query(None),
    fournisseur: str | None = Query(None),
    type_location: str | None = Query(None),
    type_cout: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(CoutFlotte)
    q = _apply_filters(q, annee, mois, plaque, type_vehicule, fournisseur, type_location)
    if type_cout:
        q = q.filter(CoutFlotte.type_cout == type_cout.upper())
    total = q.count()
    items = (
        q.order_by(CoutFlotte.plaque_immatriculation, CoutFlotte.mois, CoutFlotte.type_cout)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return CoutFlottePage(items=items, total=total)


@router.post("", response_model=CoutFlotteOut)
def create_cout(
    payload: CoutFlotteCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    cout = CoutFlotte(**payload.model_dump())
    db.add(cout)
    db.commit()
    db.refresh(cout)
    return cout


@router.patch("/{cout_id}", response_model=CoutFlotteOut)
def update_cout(
    cout_id: int,
    payload: CoutFlotteUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    cout = db.query(CoutFlotte).filter(CoutFlotte.id == cout_id).first()
    if not cout:
        raise HTTPException(404, "Coût introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(cout, key, value)
    db.commit()
    db.refresh(cout)
    return cout


@router.delete("/{cout_id}", status_code=204)
def delete_cout(
    cout_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    cout = db.query(CoutFlotte).filter(CoutFlotte.id == cout_id).first()
    if not cout:
        raise HTTPException(404, "Coût introuvable")
    db.delete(cout)
    db.commit()


@router.get("/filtres", response_model=FiltresCouts)
def filtres_couts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    def distinct(col):
        return sorted(v for (v,) in db.query(col).distinct().all() if v)

    mois = sorted(
        {m for (m,) in db.query(CoutFlotte.mois).distinct().all() if m}
    )
    return FiltresCouts(
        mois=mois,
        plaques=distinct(CoutFlotte.plaque_immatriculation),
        types_vehicule=distinct(CoutFlotte.type_vehicule),
        fournisseurs=distinct(CoutFlotte.fournisseur),
        types_location=distinct(CoutFlotte.type_location),
    )


@router.get("/kpi", response_model=KpiCouts)
def kpi_couts(
    annee: int | None = Query(None),
    mois: date | None = Query(None),
    plaque: str | None = Query(None),
    type_vehicule: str | None = Query(None),
    fournisseur: str | None = Query(None),
    type_location: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    def total_for(type_cout: str) -> float:
        q = db.query(func.coalesce(func.sum(CoutFlotte.valeur), 0)).filter(CoutFlotte.type_cout == type_cout)
        q = _apply_filters(q, annee, mois, plaque, type_vehicule, fournisseur, type_location)
        return float(q.scalar())

    cout_total = total_for("TOTAL")
    cout_distance = total_for("DISTANCE")
    return KpiCouts(
        cout_total=cout_total,
        cout_carburant=total_for("CARBURANT"),
        cout_distance=cout_distance,
        cout_par_km=(cout_total / cout_distance) if cout_distance else 0.0,
    )


@router.get("/evolution", response_model=list[EvolutionPoint])
def evolution_couts(
    type_cout: str = Query("TOTAL"),
    annee: int | None = Query(None),
    mois: date | None = Query(None),
    plaque: str | None = Query(None),
    type_vehicule: str | None = Query(None),
    fournisseur: str | None = Query(None),
    type_location: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(
        extract("year", CoutFlotte.mois).label("annee"),
        extract("month", CoutFlotte.mois).label("mois"),
        func.coalesce(func.sum(CoutFlotte.valeur), 0).label("total"),
    ).filter(CoutFlotte.type_cout == type_cout.upper())
    q = _apply_filters(q, annee, mois, plaque, type_vehicule, fournisseur, type_location)
    q = q.group_by("annee", "mois").order_by("annee", "mois")
    return [EvolutionPoint(annee=int(r.annee), mois=int(r.mois), total=float(r.total)) for r in q.all()]


@router.get("/repartition", response_model=list[RepartitionPoint])
def repartition_couts(
    annee: int | None = Query(None),
    mois: date | None = Query(None),
    plaque: str | None = Query(None),
    type_vehicule: str | None = Query(None),
    fournisseur: str | None = Query(None),
    type_location: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(
        CoutFlotte.type_cout,
        func.coalesce(func.sum(CoutFlotte.valeur), 0).label("total"),
    ).filter(CoutFlotte.type_cout.in_(TYPES_COUT_FCFA))
    q = _apply_filters(q, annee, mois, plaque, type_vehicule, fournisseur, type_location)
    q = q.group_by(CoutFlotte.type_cout).order_by(func.sum(CoutFlotte.valeur).desc())
    return [RepartitionPoint(type_cout=r.type_cout, total=float(r.total)) for r in q.all()]


@router.get("/par-vehicule", response_model=list[VehiculeCoutPoint])
def couts_par_vehicule(
    annee: int | None = Query(None),
    mois: date | None = Query(None),
    plaque: str | None = Query(None),
    type_vehicule: str | None = Query(None),
    fournisseur: str | None = Query(None),
    type_location: str | None = Query(None),
    type_cout: str = Query("TOTAL"),
    limit: int = Query(15, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(
        CoutFlotte.plaque_immatriculation,
        func.max(CoutFlotte.fournisseur).label("fournisseur"),
        func.max(CoutFlotte.type_vehicule).label("type_vehicule"),
        func.coalesce(func.sum(CoutFlotte.valeur), 0).label("total"),
    ).filter(CoutFlotte.type_cout == type_cout.upper())
    q = _apply_filters(q, annee, mois, plaque, type_vehicule, fournisseur, type_location)
    q = q.group_by(CoutFlotte.plaque_immatriculation).order_by(func.sum(CoutFlotte.valeur).desc()).limit(limit)
    return [
        VehiculeCoutPoint(
            plaque_immatriculation=r.plaque_immatriculation,
            fournisseur=r.fournisseur,
            type_vehicule=r.type_vehicule,
            total=float(r.total),
        )
        for r in q.all()
    ]


@router.get("/pivot", response_model=PivotResult)
def pivot_couts(
    group_by: str = Query(...),
    type_cout: str | None = Query("TOTAL"),
    annee: int | None = Query(None),
    mois: date | None = Query(None),
    plaque: str | None = Query(None),
    type_vehicule: str | None = Query(None),
    fournisseur: str | None = Query(None),
    type_location: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if group_by not in PIVOT_COLUMNS:
        raise HTTPException(400, f"group_by invalide. Valeurs possibles : {', '.join(PIVOT_COLUMNS)}")

    col = PIVOT_COLUMNS[group_by]
    q = db.query(col.label("label"), func.coalesce(func.sum(CoutFlotte.valeur), 0).label("total"))
    q = _apply_filters(q, annee, mois, plaque, type_vehicule, fournisseur, type_location)
    if group_by != "type_cout" and type_cout:
        q = q.filter(CoutFlotte.type_cout == type_cout.upper())
    q = q.group_by(col).order_by(col)

    items = [
        PivotPoint(label=r.label.isoformat() if isinstance(r.label, date) else (r.label or "—"), total=float(r.total))
        for r in q.all()
    ]
    return PivotResult(items=items, total=sum(i.total for i in items))


@router.post("/import", response_model=ImportCoutsResult)
async def import_couts(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet_name = next((s for s in xls.sheet_names if "DATA_FLOTTE" in s.upper()), None)
    if not sheet_name:
        raise HTTPException(400, "Feuille 'DATA_FLOTTES' introuvable dans le fichier")

    df = xls.parse(sheet_name)
    required_cols = ["TYPE DE LOCATION", "Fournisseur", "Type Vehicule", "Plaque d'immatriculation", "Mois", "Type_Cout", "Valeur"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise HTTPException(400, f"Colonnes manquantes dans '{sheet_name}': {', '.join(missing)}")

    created = 0
    updated = 0
    errors = []

    for idx, row in df.iterrows():
        try:
            plaque = str(row["Plaque d'immatriculation"]).strip()
            mois_val = row["Mois"]
            type_cout_val = row["Type_Cout"]
            if pd.isna(mois_val) or pd.isna(type_cout_val) or not plaque or plaque.lower() == "nan":
                continue

            mois: date = pd.to_datetime(mois_val).date().replace(day=1)
            type_cout = str(type_cout_val).strip().upper()
            valeur = float(row["Valeur"]) if not pd.isna(row["Valeur"]) else 0.0

            type_location = None if pd.isna(row["TYPE DE LOCATION"]) else str(row["TYPE DE LOCATION"]).strip()
            fournisseur = None if pd.isna(row["Fournisseur"]) else str(row["Fournisseur"]).strip()
            type_vehicule = None if pd.isna(row["Type Vehicule"]) else str(row["Type Vehicule"]).strip()

            existing = (
                db.query(CoutFlotte)
                .filter_by(plaque_immatriculation=plaque, mois=mois, type_cout=type_cout)
                .first()
            )
            if existing:
                existing.valeur = valeur
                existing.type_location = type_location
                existing.fournisseur = fournisseur
                existing.type_vehicule = type_vehicule
                updated += 1
            else:
                db.add(CoutFlotte(
                    type_location=type_location,
                    fournisseur=fournisseur,
                    type_vehicule=type_vehicule,
                    plaque_immatriculation=plaque,
                    mois=mois,
                    type_cout=type_cout,
                    valeur=valeur,
                ))
                created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 2, "message": str(e)})

    db.commit()
    return ImportCoutsResult(created=created, updated=updated, errors=errors)
