import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.pneumatique import Pneumatique
from ..schemas.pneumatique import (
    PneumatiqueOut, PneumatiqueCreate, PneumatiqueUpdate,
    PneumatiquePage, ImportPneumatiqueResult, FiltresPneumatiques,
)
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/pneumatiques", tags=["Flotte — Pneumatiques"])

SECTION_KEYWORDS = ["ETS ", "AUTORENT", "LASA", "MALEYE", "GARAGE", "SOCIET", "CONCESS"]
TYPE_LOCATION_KEYWORDS = ["CAMUSAT", "LLD", "LCD", "AUTORENT", "AUTRENT", "LASA"]


def _apply_filters(q, fournisseur, immatriculation, etat, snc, search):
    if fournisseur:
        q = q.filter(Pneumatique.fournisseur == fournisseur)
    if immatriculation:
        q = q.filter(Pneumatique.immatriculation == immatriculation)
    if etat:
        q = q.filter(Pneumatique.etat == etat)
    if snc:
        q = q.filter(Pneumatique.snc == snc)
    if search:
        like = f"%{search}%"
        q = q.filter(
            Pneumatique.immatriculation.ilike(like) |
            Pneumatique.chauffeur.ilike(like) |
            Pneumatique.fournisseur.ilike(like) |
            Pneumatique.ref_pneu.ilike(like) |
            Pneumatique.zone_intervention.ilike(like)
        )
    return q


@router.get("/filtres", response_model=FiltresPneumatiques)
def get_filtres(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    def distinct(col):
        return sorted({v for (v,) in db.query(col).distinct().all() if v})
    return FiltresPneumatiques(
        fournisseurs=distinct(Pneumatique.fournisseur),
        immatriculations=distinct(Pneumatique.immatriculation),
        etats=distinct(Pneumatique.etat),
        sncs=distinct(Pneumatique.snc),
    )


@router.get("", response_model=PneumatiquePage)
def list_pneumatiques(
    fournisseur: str | None = None,
    immatriculation: str | None = None,
    etat: str | None = None,
    snc: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = _apply_filters(db.query(Pneumatique), fournisseur, immatriculation, etat, snc, search)
    total = q.count()
    items = (
        q.order_by(Pneumatique.fournisseur, Pneumatique.immatriculation)
         .offset((page - 1) * page_size)
         .limit(page_size)
         .all()
    )
    return PneumatiquePage(items=items, total=total)


@router.post("", response_model=PneumatiqueOut, status_code=201)
def create_pneumatique(
    data: PneumatiqueCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    p = Pneumatique(**data.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.patch("/{item_id}", response_model=PneumatiqueOut)
def update_pneumatique(
    item_id: int,
    data: PneumatiqueUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    p = db.query(Pneumatique).filter(Pneumatique.id == item_id).first()
    if not p:
        raise HTTPException(404, "Pneumatique introuvable")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return p


@router.delete("/{item_id}", status_code=204)
def delete_pneumatique(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    p = db.query(Pneumatique).filter(Pneumatique.id == item_id).first()
    if not p:
        raise HTTPException(404, "Pneumatique introuvable")
    db.delete(p); db.commit()


@router.post("/import", response_model=ImportPneumatiqueResult)
async def import_pneumatiques(
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
        (s for s in xls.sheet_names if "PNEUM" in s.upper()),
        None
    )
    if not sheet_name:
        raise HTTPException(400, "Feuille 'PNEUMATIQUE' introuvable dans le fichier")

    df = xls.parse(sheet_name, header=None)

    current_fournisseur = None
    col_map: dict[str, int] = {}
    created = 0
    updated = 0
    errors = []

    def gs(v) -> str:
        """Get clean string."""
        if pd.isna(v):
            return ""
        s = str(v).strip()
        return "" if s.upper() in ("NAN", "N/A", "NA", "NONE") else s

    def gf(ci: int):
        """Get float from column index."""
        if ci >= len(row.values):
            return None
        v = row.values[ci]
        if pd.isna(v):
            return None
        try:
            return float(v)
        except Exception:
            return None

    def gd(ci: int):
        """Get date from column index."""
        if ci >= len(row.values):
            return None
        v = row.values[ci]
        if pd.isna(v):
            return None
        try:
            return pd.to_datetime(v, dayfirst=True).date()
        except Exception:
            try:
                return pd.to_datetime(str(v).strip(), dayfirst=True).date()
            except Exception:
                return None

    for idx, row in df.iterrows():
        vals = [gs(v) for v in row.values]
        col_a = vals[0] if vals else ""
        col_b = vals[1] if len(vals) > 1 else ""
        col_c = vals[2] if len(vals) > 2 else ""

        # Skip fully empty rows
        if not any(vals):
            continue

        # Section header detection: col A empty, col B or C has supplier name
        if not col_a:
            candidate = col_b or col_c
            cand_up = candidate.upper()
            if candidate and any(kw in cand_up for kw in SECTION_KEYWORDS):
                current_fournisseur = candidate
                col_map = {}
            continue

        # Column header row detection
        if col_a.upper() in ("IMMA", "IMMATRICULATION", "PLAQUE"):
            col_map = {}
            for ci, v in enumerate(vals):
                vu = v.upper()
                if any(k in vu for k in ("IMMA", "PLAQUE")):
                    col_map["immatriculation"] = ci
                elif "CHAUFF" in vu:
                    col_map["chauffeur"] = ci
                elif "KILOM" in vu:
                    col_map["kilometrage"] = ci
                elif "PNEU" in vu and ci != col_map.get("ref_pneu"):
                    col_map["nb_pneus"] = ci
                elif "REF" in vu:
                    col_map["ref_pneu"] = ci
                elif "ETAT" in vu:
                    col_map["etat"] = ci
                elif "SNC" in vu:
                    col_map["snc"] = ci
                elif "ZONE" in vu or "INTERVENTION" in vu or "FOOR" in vu:
                    col_map["zone_intervention"] = ci
                elif "DATE" in vu and "PREV" in vu:
                    col_map["date_prevue"] = ci
                elif "COMMENT" in vu:
                    col_map["commentaire"] = ci
            continue

        # Data row — skip if col A looks like a NaT/NaN sentinel or header is missing
        if not col_a or col_a.upper() in ("NAT", "NAN", "N/A", "NA", "NONE"):
            continue
        if "immatriculation" not in col_map:
            continue

        try:
            imma_ci = col_map["immatriculation"]
            imma = gs(row.values[imma_ci]) if imma_ci < len(row.values) else ""
            if not imma or imma.upper() in ("NAT", "NAN", "N/A", "NA"):
                continue

            def get_s(field: str) -> str | None:
                ci = col_map.get(field)
                if ci is None:
                    return None
                v = gs(row.values[ci]) if ci < len(row.values) else ""
                return v or None

            # Col 2 may hold either kilométrage (numeric) or type_location ("CAMUSAT", "LLD"…)
            km_ci = col_map.get("kilometrage")
            row_km: float | None = None
            row_type_loc: str | None = None
            if km_ci is not None and km_ci < len(row.values):
                raw_km = row.values[km_ci]
                km_float = gf(km_ci)
                if km_float is not None:
                    row_km = km_float
                else:
                    raw_str = gs(raw_km)
                    if raw_str and any(kw in raw_str.upper() for kw in TYPE_LOCATION_KEYWORDS):
                        row_type_loc = raw_str

            nb = None
            if "nb_pneus" in col_map:
                v_nb = gf(col_map["nb_pneus"])
                nb = int(v_nb) if v_nb is not None else None

            values = dict(
                fournisseur=current_fournisseur,
                type_location=row_type_loc,
                immatriculation=imma,
                chauffeur=get_s("chauffeur"),
                kilometrage=row_km,
                nb_pneus=nb,
                ref_pneu=get_s("ref_pneu"),
                etat=get_s("etat"),
                snc=get_s("snc"),
                zone_intervention=get_s("zone_intervention"),
                date_prevue=gd(col_map["date_prevue"]) if "date_prevue" in col_map else None,
                commentaire=get_s("commentaire"),
            )

            # Upsert: unique by (immatriculation, fournisseur)
            existing = db.query(Pneumatique).filter(
                Pneumatique.immatriculation == imma,
                Pneumatique.fournisseur == current_fournisseur,
            ).first()

            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(Pneumatique(**values))
                created += 1

        except Exception as e:
            errors.append({"ligne": int(idx) + 1, "message": str(e)})

    db.commit()
    return ImportPneumatiqueResult(created=created, updated=updated, errors=errors)
