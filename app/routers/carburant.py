import io
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models.carburant import Carburant
from ..models.user import User
from ..schemas.carburant import CarburantOut, CarburantPage, CarburantStats, CarburantUpdate, ImportCarburantResult
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
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Carburant)
    if car_group:
        q = q.filter(Carburant.car_group == car_group)
    if type_carburant:
        q = q.filter(func.upper(Carburant.type_carburant) == type_carburant.upper())

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

@router.post("/import", response_model=ImportCarburantResult)
async def import_carburant(
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
        (s for s in xls.sheet_names if "CARBURANT" in s.strip().upper()),
        None,
    )
    if not sheet_name:
        raise HTTPException(400, "Feuille 'CARBURANT' introuvable dans le fichier")

    # Lecture avec header=0, la colonne sans nom (type carburant) sera Unnamed: 5
    df = xls.parse(sheet_name, header=0)
    df.columns = [str(c).strip() for c in df.columns]

    # Identifier la colonne type carburant (colonne sans entête entre PrixUnitaire et DistanceTotale)
    type_col = next(
        (c for c in df.columns if "Unnamed" in c or c.upper() in ("TYPE", "CARBURANT", "TYPE CARBURANT")),
        None,
    )

    # Preload existing rows keyed by matricule (un enregistrement par véhicule/import)
    existing_map: dict[str, Carburant] = {
        r.matricule: r for r in db.query(Carburant).all()
    }

    created = 0
    updated = 0
    errors: list[dict] = []

    for idx, row in df.iterrows():
        matr = _cs(row.get("Matricule"))
        if not matr:
            continue

        # Ignorer les lignes de totaux / sous-totaux
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

            existing = existing_map.get(matr)
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                new_r = Carburant(**values)
                db.add(new_r)
                existing_map[matr] = new_r
                created += 1

        except Exception as e:
            errors.append({"ligne": int(idx) + 2, "message": str(e)})

    db.commit()
    return ImportCarburantResult(created=created, updated=updated, errors=errors)
