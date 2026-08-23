import io
import calendar
from datetime import date as DateType, date

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.suivi_panne import SuiviPanne
from ..models.vehicule import Vehicule
from ..models.carburant import Carburant
from ..models.recap_panne import RecapPanneVehicule
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
    if statut:
        # Filtre sur le vrai champ statut (EN_COURS / REPARE / A_CONFIRMER)
        # Rétrocompat : si pas de statut enregistré, fallback sur date_fin_reparation
        if statut == "REPARE":
            q = q.filter(SuiviPanne.statut == "REPARE")
        elif statut == "EN_COURS":
            q = q.filter(SuiviPanne.statut == "EN_COURS")
        elif statut == "A_CONFIRMER":
            q = q.filter(SuiviPanne.statut == "A_CONFIRMER")
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


@router.get("/recap")
def recap_pannes(
    annee: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Pivot : statut mensuel des véhicules.
    Priorité : données importées depuis la feuille 'RECAP DES PANNES'.
    Fallback : calcul dynamique depuis les pannes enregistrées."""
    import unicodedata
    def _norm(val: str | None) -> str:
        if not val:
            return ""
        s = unicodedata.normalize("NFD", val.strip())
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return s.upper().replace(" ", "_").replace("-", "_")

    today = date.today()
    year = annee or today.year

    # ── Compter les statuts actuels depuis vehicules ──────────────────────────
    all_vehicules = db.query(Vehicule).all()
    vehicule_map: dict[str, Vehicule] = {v.plaque_immatriculation: v for v in all_vehicules}
    en_service = en_maintenance = immobilises = 0
    for v in all_vehicules:
        n = _norm(v.statut)
        if n == "EN_SERVICE":
            en_service += 1
        elif n == "EN_MAINTENANCE":
            en_maintenance += 1
        elif n.startswith("IMMOBILISE"):
            immobilises += 1

    # ── Données importées (feuille RECAP DES PANNES) ─────────────────────────
    recap_rows = db.query(RecapPanneVehicule).order_by(RecapPanneVehicule.plaque_immatriculation).all()

    if recap_rows:
        # Filtrer les mois de l'année demandée présents dans les données
        all_mois: set[str] = set()
        for row in recap_rows:
            for iso in (row.statuts_mensuels or {}).keys():
                if iso.startswith(str(year)):
                    all_mois.add(iso)

        # Si aucun mois de cette année dans les données, générer des mois vides
        if not all_mois:
            max_month = today.month if year == today.year else 12
            all_mois = {f"{year}-{m:02d}" for m in range(1, max_month + 1)}

        mois = sorted(all_mois)
        car_group_map: dict[str, str] = {
            r.matricule: r.car_group
            for r in db.query(Carburant.matricule, Carburant.car_group).all()
            if r.matricule and r.car_group
        }

        result_vehicules = []
        for row in recap_rows:
            veh = vehicule_map.get(row.plaque_immatriculation)
            statuts = {
                iso: (row.statuts_mensuels or {}).get(iso)
                for iso in mois
            }
            result_vehicules.append({
                "id": row.id,
                "immatriculation": row.plaque_immatriculation,
                "marque": row.brand or (veh.marque if veh else None),
                "modele": row.model or (veh.modele if veh else None),
                "chauffeur": row.label or (veh.chauffeur if veh else None),
                "type_carburant": row.fuel_type or (veh.type_carburant if veh else None),
                "car_group": row.car_group or car_group_map.get(row.plaque_immatriculation),
                "statut_actuel": veh.statut if veh else None,
                "statuts": statuts,
            })

        return {
            "annee": year,
            "mois": mois,
            "vehicules": result_vehicules,
            "source": "import",
            "stats": {
                "en_service": en_service,
                "en_maintenance": en_maintenance,
                "immobilises": immobilises,
                "total": len(all_vehicules),
            },
        }

    # ── Fallback : calcul dynamique depuis suivi_pannes ───────────────────────
    max_month = today.month if year == today.year else 12
    mois = [f"{year}-{m:02d}" for m in range(1, max_month + 1)]

    pannes = db.query(SuiviPanne).all()
    car_group_map = {
        r.matricule: r.car_group
        for r in db.query(Carburant.matricule, Carburant.car_group).all()
        if r.matricule and r.car_group
    }

    from collections import defaultdict
    pannes_by_immat: dict[str, list] = defaultdict(list)
    for p in pannes:
        pannes_by_immat[p.immatriculation].append(p)

    def statut_mois(immat: str, iso_mois: str) -> str:
        y, m = int(iso_mois.split("-")[0]), int(iso_mois.split("-")[1])
        first = date(y, m, 1)
        last = date(y, m, calendar.monthrange(y, m)[1])
        for p in pannes_by_immat.get(immat, []):
            if p.date_indisponibilite is None:
                continue
            if p.date_indisponibilite <= last and (p.date_fin_reparation is None or p.date_fin_reparation >= first):
                return "En maintenance"
        return "En service"

    result_vehicules = []
    for v in sorted(all_vehicules, key=lambda x: x.plaque_immatriculation):
        statuts = {m: statut_mois(v.plaque_immatriculation, m) for m in mois}
        result_vehicules.append({
            "id": None,
            "immatriculation": v.plaque_immatriculation,
            "marque": v.marque,
            "modele": v.modele,
            "chauffeur": v.chauffeur,
            "type_carburant": v.type_carburant,
            "car_group": car_group_map.get(v.plaque_immatriculation),
            "statut_actuel": v.statut,
            "statuts": statuts,
        })

    return {
        "annee": year,
        "mois": mois,
        "vehicules": result_vehicules,
        "source": "computed",
        "stats": {
            "en_service": en_service,
            "en_maintenance": en_maintenance,
            "immobilises": immobilises,
            "total": len(all_vehicules),
        },
    }


@router.patch("/recap/by-plaque/{plaque}")
def update_recap_by_plaque(
    plaque: str,
    payload: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    """Upsert : crée la ligne recap si elle n'existe pas, puis met à jour."""
    row = db.query(RecapPanneVehicule).filter(
        RecapPanneVehicule.plaque_immatriculation == plaque
    ).first()
    if not row:
        row = RecapPanneVehicule(plaque_immatriculation=plaque, statuts_mensuels={})
        db.add(row)
        db.flush()
    return _apply_recap_patch(row, payload, db)


@router.patch("/recap/{recap_id}")
def update_recap_vehicule(
    recap_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    row = db.get(RecapPanneVehicule, recap_id)
    if not row:
        raise HTTPException(404, "Enregistrement recap introuvable")
    return _apply_recap_patch(row, payload, db)


def _apply_recap_patch(row: RecapPanneVehicule, payload: dict, db: Session) -> dict:
    FIXED_FIELDS = {"brand", "model", "label", "fuel_type", "car_group", "sorti"}
    statuts = dict(row.statuts_mensuels or {})

    for key, value in payload.items():
        if key in FIXED_FIELDS:
            if key == "sorti":
                setattr(row, key, bool(value))
            else:
                setattr(row, key, value or None)
        elif len(key) == 7 and key[4] == "-":  # YYYY-MM
            statuts[key] = value or None

    row.statuts_mensuels = statuts

    if any(len(k) == 7 and k[4] == "-" for k in payload):
        veh = db.query(Vehicule).filter(
            Vehicule.plaque_immatriculation == row.plaque_immatriculation
        ).first()
        if veh and statuts:
            dernier = max(statuts.keys())
            if statuts.get(dernier):
                veh.statut = statuts[dernier]

    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "plaque_immatriculation": row.plaque_immatriculation,
        "brand": row.brand,
        "model": row.model,
        "label": row.label,
        "fuel_type": row.fuel_type,
        "car_group": row.car_group,
        "sorti": row.sorti,
        "statuts_mensuels": row.statuts_mensuels,
    }


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
