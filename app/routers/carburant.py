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

router = APIRouter(prefix="/api/carburant", tags=["Carburant"])


def _cs(v) -> str | None:
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s and s.upper() not in ("NAN", "N/A", "NA", "NONE", "NAT") else None


def _cf(v) -> float | None:
    if pd.isna(v):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _cd(v):
    if pd.isna(v):
        return None
    try:
        return pd.to_datetime(v, dayfirst=True).date()
    except Exception:
        return None


# ── Filtres disponibles ────────────────────────────────────────────────────────

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
    if mois is not None:
        q = q.filter(Carburant.mois == mois)

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
        total_vehicules=len(rows),
        total_litres=round(total_litres, 2),
        total_montant=round(total_montant, 2),
        total_distance=round(total_distance, 2),
        nb_gazoil=len(gazoil),
        nb_essence=len(essence),
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
    ).first()
    if existing:
        raise HTTPException(409, "Une entrée existe déjà pour ce matricule et ce mois.")
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


# ── Noms de mois pour la détection automatique ────────────────────────────────

_MOIS_FR = {
    "JANVIER": 1, "FEVRIER": 2, "FÉVRIER": 2, "MARS": 3, "AVRIL": 4,
    "MAI": 5, "JUIN": 6, "JUILLET": 7, "AOUT": 8, "AOÛT": 8,
    "SEPTEMBRE": 9, "OCTOBRE": 10, "NOVEMBRE": 11, "DECEMBRE": 12, "DÉCEMBRE": 12,
    "JAN": 1, "FEV": 2, "FÉV": 2, "MAR": 3, "AVR": 4,
    "JUI": 6, "JUL": 7, "AOU": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12, "DÉC": 12,
}


def _detect_mois(filename: str, xls: pd.ExcelFile, sheet_name: str) -> int | None:
    """Essaie de détecter le mois depuis le nom de fichier ou la feuille Excel."""
    import re

    # 1. Cherche dans le nom du fichier
    name_upper = filename.upper().replace("_", " ").replace("-", " ")
    for token in re.split(r"[\s\.]+", name_upper):
        if token in _MOIS_FR:
            return _MOIS_FR[token]

    # 2. Cherche dans le nom de la feuille
    sheet_upper = sheet_name.upper().replace("_", " ").replace("-", " ")
    for token in re.split(r"[\s\.]+", sheet_upper):
        if token in _MOIS_FR:
            return _MOIS_FR[token]

    # 3. Cherche dans les 5 premières lignes des premières colonnes
    try:
        df_head = xls.parse(sheet_name, header=None, nrows=5)
        for row in df_head.itertuples(index=False):
            for cell in row:
                if pd.isna(cell):
                    continue
                for token in re.split(r"[\s/\-_\.]+", str(cell).upper()):
                    if token in _MOIS_FR:
                        return _MOIS_FR[token]
    except Exception:
        pass

    # 4. Cherche dans la colonne DernierPlein — mois le plus fréquent
    try:
        df_sample = xls.parse(sheet_name, header=0)
        df_sample.columns = [str(c).strip() for c in df_sample.columns]
        col = next((c for c in df_sample.columns if "DERNIER" in c.upper() or "PLEIN" in c.upper()), None)
        if col:
            dates = pd.to_datetime(df_sample[col], errors="coerce", dayfirst=True).dropna()
            if not dates.empty:
                return int(dates.dt.month.mode()[0])
    except Exception:
        pass

    return None


# ── Import Excel ───────────────────────────────────────────────────────────────

@router.post("/import", response_model=ImportCarburantResult)
async def import_carburant(
    file: UploadFile = File(...),
    mois: int = Query(1, ge=1, le=12, description="Mois de l'import (1=Janvier … 12=Décembre)"),
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet_name = next(
        (s for s in xls.sheet_names if "CARBURANT" in s.strip().upper()),
        None,
    )
    if not sheet_name:
        raise HTTPException(400, "Feuille 'CARBURANT' introuvable dans le fichier")

    # Auto-détection du mois depuis le fichier (priorité sur le paramètre par défaut)
    detected = _detect_mois(file.filename or "", xls, sheet_name)
    if detected:
        mois = detected

    df = xls.parse(sheet_name, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    type_col = next(
        (c for c in df.columns if "Unnamed" in c or c.upper() in ("TYPE", "CARBURANT", "TYPE CARBURANT")),
        None,
    )

    # Clé unique = (matricule, mois) — un véhicule peut avoir un enregistrement par mois
    existing_map: dict[tuple[str, int], Carburant] = {
        (r.matricule, r.mois): r for r in db.query(Carburant).filter(Carburant.mois == mois).all()
    }

    created = 0
    updated = 0
    errors: list[dict] = []

    for idx, row in df.iterrows():
        matr = _cs(row.get("Matricule"))
        if not matr:
            continue
        if any(kw in matr.upper() for kw in ("TOTAL", "SOUS-TOTAL", "GRAND TOTAL")):
            continue

        type_carb = None
        if type_col:
            raw = _cs(row.get(type_col))
            if raw and raw.upper() in ("GAZOIL", "ESSENCE"):
                type_carb = raw.upper()

        try:
            values = dict(
                matricule       = matr,
                mois            = mois,
                quantite_totale = _cf(row.get("QuantiteTotale")),
                montant_total   = _cf(row.get("MontantTotal")),
                mt_ht           = _cf(row.get("Mt HT")),
                prix_unitaire   = _cf(row.get("PrixUnitaire")),
                type_carburant  = type_carb,
                distance_totale = _cf(row.get("DistanceTotale")),
                distance_gps    = _cf(row.get("Distance GPS")),
                car_group       = _cs(row.get("CarGroup")),
                dernier_plein   = _cd(row.get("DernierPlein")),
                driver_name     = _cs(row.get("DriverName")),
                nom_chauffeur   = _cs(row.get("Nom de chauffeur")),
                code_projet     = _cs(row.get("CodeProjet")),
                num_carte       = _cs(row.get("NumCarte")),
            )

            key = (matr, mois)
            existing = existing_map.get(key)
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                new_r = Carburant(**values)
                db.add(new_r)
                existing_map[key] = new_r
                created += 1

        except Exception as e:
            errors.append({"ligne": int(idx) + 2, "message": str(e)})

    db.commit()
    return ImportCarburantResult(created=created, updated=updated, errors=errors, mois_detecte=mois)
