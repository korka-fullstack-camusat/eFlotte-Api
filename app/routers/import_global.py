"""
Import global — lit le fichier Excel une seule fois et alimente
automatiquement toutes les rubriques de l'application.
"""
import io
from datetime import date as DateType

import pandas as pd
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.import_global_log import ImportGlobalLog
from ..models.vehicule import Vehicule
from ..models.cout_flotte import CoutFlotte
from ..models.mission_chauffeur import MissionChauffeur
from ..models.suivi_devis import SuiviDevis
from ..models.checklist_vl import CheckListVL
from ..models.entretien import EntretienVehicule
from ..models.entretien_bis import EntretienBis
from ..models.suivi_panne import SuiviPanne
from ..models.pneumatique import Pneumatique
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/import-global", tags=["Import global"])

PALIERS_KM = [7500, 15000, 22500, 30000, 37500, 45000, 52500, 60000,
               67500, 75000, 82500, 90000, 97500, 105000]
PALIERS_KM_BIS = [112500, 120000, 135000, 142500, 150000,
                   157500, 165000, 172500, 180000, 187500, 195000, 202500]
SECTION_KEYWORDS_PNE = ["ETS ", "AUTORENT", "LASA", "MALEYE", "GARAGE", "SOCIET", "CONCESS"]
TYPE_LOCATION_KEYWORDS = ["CAMUSAT", "LLD", "LCD", "AUTORENT", "AUTRENT", "LASA"]


class SectionResult(BaseModel):
    created: int = 0
    updated: int = 0
    errors: list[dict] = []
    skipped: bool = False
    skip_reason: str = ""


class ImportGlobalResult(BaseModel):
    vehicules: SectionResult
    couts: SectionResult
    missions: SectionResult
    devis: SectionResult
    checklists: SectionResult
    entretiens: SectionResult
    entretiens_bis: SectionResult
    pannes: SectionResult
    pneumatiques: SectionResult


class ImportGlobalLogOut(BaseModel):
    id: int
    created_at: str
    username: str | None
    filename: str | None
    total_created: int
    total_updated: int
    total_errors: int
    results: dict

    model_config = {"from_attributes": True}


# ── helpers ──────────────────────────────────────────────────────────────────

def _cs(v) -> str | None:
    """Clean string."""
    if pd.isna(v): return None
    s = str(v).strip()
    return s if s and s.upper() not in ("NAN", "N/A", "NA", "NONE", "NAT") else None


def _cd(v) -> DateType | None:
    """Clean date."""
    if pd.isna(v): return None
    try:
        return pd.to_datetime(v, dayfirst=True).date()
    except Exception:
        return None


def _cf(v) -> float | None:
    """Clean float."""
    if pd.isna(v): return None
    try:
        return float(v)
    except Exception:
        return None


# ── parsers ──────────────────────────────────────────────────────────────────

def _vehicules(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "FLOTTE GLOBALE" in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'FLOTTE GLOBALE' introuvable"; return r
    try:
        df = xls.parse(sheet, header=0)
        df.columns = [str(c).strip() for c in df.columns]
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    col_plaque = next((c for c in df.columns if "PLAQUE" in c.upper() or "IMMATRICULATION" in c.upper()), None)
    if not col_plaque:
        r.skipped = True; r.skip_reason = "Colonne plaque introuvable"; return r

    col_map = {
        "type_location": next((c for c in df.columns if "TYPE DE LOCATION" in c.upper() or "TYPE DE LOCAT" in c.upper()), None),
        "fournisseur":   next((c for c in df.columns if c.strip().lower() in ("fournisseur",)), None),
        "type_vehicule": next((c for c in df.columns if "TYPE VEHICULE" in c.upper() or "TYPE VÉ" in c.upper()), None),
        "n_chassis":     next((c for c in df.columns if "CHASSIS" in c.upper()), None),
        "modele":        next((c for c in df.columns if "MODEL" in c.upper()), None),
        "couleur":       next((c for c in df.columns if "COULEUR" in c.upper()), None),
        "autocollant":   next((c for c in df.columns if "AUTOCOL" in c.upper()), None),
        "grille":        next((c for c in df.columns if c.strip().upper() == "GRILLE"), None),
        "croche":        next((c for c in df.columns if c.strip().upper() == "CROCHE"), None),
        "extincteurs":   next((c for c in df.columns if "EXTINC" in c.upper()), None),
        "trousse_secours": next((c for c in df.columns if "TROUSSE" in c.upper()), None),
        "peage":         next((c for c in df.columns if c.strip().upper() == "PEAGE"), None),
        "carte_carburant": next((c for c in df.columns if "CARTE" in c.upper() and "CARB" in c.upper()), None),
    }

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_plaque])
            if not plaque:
                continue
            vals = {k: _cs(row[v]) if v and v in df.columns and not pd.isna(row[v]) else None
                    for k, v in col_map.items()}
            existing = db.query(Vehicule).filter_by(plaque_immatriculation=plaque).first()
            if existing:
                for k, v in vals.items():
                    if v is not None:
                        setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(Vehicule(plaque_immatriculation=plaque, **vals))
                r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 2, "message": str(e)})
    db.commit()
    return r


def _couts(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "DATA_FLOTTE" in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'DATA_FLOTTES' introuvable"; return r
    try:
        df = xls.parse(sheet, header=0)
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    required = {"Plaque d'immatriculation", "Mois", "Type_Cout", "Valeur"}
    if not required.issubset(set(df.columns)):
        r.skipped = True; r.skip_reason = f"Colonnes manquantes : {required - set(df.columns)}"; return r

    for idx, row in df.iterrows():
        try:
            plaque = str(row["Plaque d'immatriculation"]).strip()
            mois_val = row["Mois"]
            type_cout_val = row["Type_Cout"]
            if pd.isna(mois_val) or pd.isna(type_cout_val) or not plaque or plaque.lower() == "nan":
                continue
            mois: DateType = pd.to_datetime(mois_val).date().replace(day=1)
            type_cout = str(type_cout_val).strip().upper()
            valeur = float(row["Valeur"]) if not pd.isna(row["Valeur"]) else 0.0
            type_location = _cs(row.get("TYPE DE LOCATION") or row.get("TYPE DE LOCAT"))
            fournisseur   = _cs(row.get("Fournisseur"))
            type_vehicule = _cs(row.get("Type Vehicule"))
            existing = db.query(CoutFlotte).filter_by(
                plaque_immatriculation=plaque, mois=mois, type_cout=type_cout
            ).first()
            if existing:
                existing.valeur = valeur
                existing.type_location = type_location
                existing.fournisseur   = fournisseur
                existing.type_vehicule = type_vehicule
                r.updated += 1
            else:
                db.add(CoutFlotte(type_location=type_location, fournisseur=fournisseur,
                                   type_vehicule=type_vehicule, plaque_immatriculation=plaque,
                                   mois=mois, type_cout=type_cout, valeur=valeur))
                r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 2, "message": str(e)})
    db.commit()
    return r


def _missions(xls: pd.ExcelFile, db: Session) -> SectionResult:
    from datetime import datetime
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "CHAUFFEUR" in s.upper() and "POLE" in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'CHAUFFEUR POLES' introuvable"; return r
    try:
        df = xls.parse(sheet, header=1)
        df.columns = [str(c).strip() for c in df.columns]
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    required = {"DATE", "IMMA", "CHAUFFEUR", "DEMANDEUR", "PROJET", "DESTINATION"}
    if not required.issubset(set(df.columns)):
        r.skipped = True; r.skip_reason = f"Colonnes manquantes : {required - set(df.columns)}"; return r

    def pd_(v) -> DateType | None:
        if pd.isna(v) or not isinstance(v, (pd.Timestamp, datetime)): return None
        return pd.to_datetime(v).date()

    for idx, row in df.iterrows():
        try:
            mission_date = pd_(row["DATE"])
            imma = _cs(row["IMMA"])
            if not mission_date or not imma:
                continue
            vals = dict(
                date=mission_date, immatriculation=imma,
                chauffeur=_cs(row.get("CHAUFFEUR")), demandeur=_cs(row.get("DEMANDEUR")),
                telephone=_cs(row.get("TELEPHONE")), projet=_cs(row.get("PROJET")),
                destination=_cs(row.get("DESTINATION")),
                date_depart=pd_(row.get("DATE DEPART")), date_retour=pd_(row.get("DATE RETOUR")),
                commentaires=_cs(row.get("COMMENTAIRES")),
            )
            existing = db.query(MissionChauffeur).filter_by(
                date=mission_date, immatriculation=imma,
                demandeur=vals["demandeur"], destination=vals["destination"]
            ).first()
            if existing:
                for k, v in vals.items(): setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(MissionChauffeur(**vals)); r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 3, "message": str(e)})
    db.commit()
    return r


def _devis(xls: pd.ExcelFile, db: Session) -> SectionResult:
    from datetime import datetime
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "SUIVI" in s.upper() and "DEVIS" in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'SUIVI DES DEVIS' introuvable"; return r
    try:
        df = xls.parse(sheet, header=4)
        df.columns = [" ".join(str(c).split()) for c in df.columns]
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    if "DESCRIPTIONS" not in df.columns:
        r.skipped = True; r.skip_reason = "Colonne DESCRIPTIONS introuvable"; return r

    col_map = {
        "descriptions":  next((c for c in df.columns if "DESCRIPTION" in c.upper()), None),
        "numero_devis":  next((c for c in df.columns if "DEVIS" in c.upper() and ("N°" in c or "#" in c)), None),
        "valeur_devis":  next((c for c in df.columns if "VALEUR" in c.upper() and "DEVIS" in c.upper()), None),
        "date":          next((c for c in df.columns if c.strip().upper() == "DATE"), None),
        "montant":       next((c for c in df.columns if c.strip().upper() == "MONTANT"), None),
        "sous_traitant": next((c for c in df.columns if "SOUS-TRAIT" in c.upper() or "SUPPLIER" in c.upper()), None),
        "matricule":     next((c for c in df.columns if c.strip().upper() == "MATRICULE"), None),
        "code_snc":      next((c for c in df.columns if "CODE SNC" in c.upper()), None),
        "po_emis":       next((c for c in df.columns if "PO EMIS" in c.upper()), None),
    }

    def pd_(v) -> DateType | None:
        if pd.isna(v): return None
        if isinstance(v, (pd.Timestamp, datetime)): return v.date()
        try: return pd.to_datetime(v, dayfirst=True).date()
        except: return None

    for idx, row in df.iterrows():
        try:
            desc = _cs(row[col_map["descriptions"]]) if col_map["descriptions"] else None
            if not desc: continue
            vals = dict(
                descriptions=desc,
                numero_devis=_cs(row[col_map["numero_devis"]]) if col_map["numero_devis"] else None,
                valeur_devis=_cf(row[col_map["valeur_devis"]]) if col_map["valeur_devis"] else None,
                date=pd_(row[col_map["date"]]) if col_map["date"] else None,
                montant=_cf(row[col_map["montant"]]) if col_map["montant"] else None,
                sous_traitant=_cs(row[col_map["sous_traitant"]]) if col_map["sous_traitant"] else None,
                matricule=_cs(row[col_map["matricule"]]) if col_map["matricule"] else None,
                code_snc=_cs(row[col_map["code_snc"]]) if col_map["code_snc"] else None,
                po_emis=_cs(row[col_map["po_emis"]]) if col_map["po_emis"] else None,
            )
            existing = db.query(SuiviDevis).filter_by(
                descriptions=desc,
                numero_devis=vals["numero_devis"],
            ).first()
            if existing:
                for k, v in vals.items(): setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(SuiviDevis(**vals)); r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 5, "message": str(e)})
    db.commit()
    return r


def _checklists(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "CHECK" in s.upper() and "LIST" in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'SUIVI DES CHECK LISTS VL' introuvable"; return r
    try:
        df = xls.parse(sheet, header=1)
        df.columns = [" ".join(str(c).split()) for c in df.columns]
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    col_plaque = next((c for c in df.columns if "REG" in c.upper() or "PLAQUE" in c.upper() or "IMMA" in c.upper()), None)
    if not col_plaque:
        r.skipped = True; r.skip_reason = "Colonne plaque introuvable"; return r

    # Colonnes semaines = tout ce qui n'est pas une colonne fixe connue
    fixed = {"Brand", "Model", col_plaque, "Label", "Car Group"}
    semaine_cols = [c for c in df.columns if c not in fixed and str(c).strip()]

    seen: dict[str, CheckListVL] = {}

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_plaque])
            if not plaque: continue
            semaines = {}
            for s in semaine_cols:
                v = _cs(row[s])
                semaines[s] = v
            vals = dict(
                brand=_cs(row.get("Brand")), model=_cs(row.get("Model")),
                label=_cs(row.get("Label")), car_group=_cs(row.get("Car Group")),
                semaines=semaines,
            )
            existing = seen.get(plaque) or db.query(CheckListVL).filter_by(plaque_immatriculation=plaque).first()
            if existing:
                for k, v in vals.items(): setattr(existing, k, v)
                if plaque not in seen: r.updated += 1
                seen[plaque] = existing
            else:
                obj = CheckListVL(plaque_immatriculation=plaque, **vals)
                db.add(obj); seen[plaque] = obj; r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 3, "message": str(e)})
    db.commit()
    return r


def _entretiens(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "ENTRTIEN" in s.upper().replace(" ", "") and "BIS" not in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'ENTRTIENS' introuvable"; return r
    try:
        df = xls.parse(sheet, header=2)
        cols = list(df.columns)
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    if len(cols) < 5 + len(PALIERS_KM):
        r.skipped = True; r.skip_reason = "Structure inattendue"; return r

    col_tl, col_f, col_tv, col_mat, col_nom = cols[:5]
    col_paliers = cols[5:5 + len(PALIERS_KM)]
    col_reste = cols[5 + len(PALIERS_KM)] if len(cols) > 5 + len(PALIERS_KM) else None

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_mat])
            if not plaque: continue
            paliers = {str(km): (_cf(row[col]) if not pd.isna(row[col]) else None)
                       for km, col in zip(PALIERS_KM, col_paliers)}
            vals = dict(
                type_location=_cs(row[col_tl]), fournisseur=_cs(row[col_f]),
                type_vehicule=_cs(row[col_tv]), nom_chauffeur=_cs(row[col_nom]),
                paliers=paliers,
                reste=_cf(row[col_reste]) if col_reste and not pd.isna(row[col_reste]) else None,
            )
            existing = db.query(EntretienVehicule).filter_by(plaque_immatriculation=plaque).first()
            if existing:
                for k, v in vals.items(): setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(EntretienVehicule(plaque_immatriculation=plaque, **vals)); r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 4, "message": str(e)})
    db.commit()
    return r


def _entretiens_bis(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "ENTRETIEN BIS" in s.upper() or "ENTRETIEN_BIS" in s.upper().replace(" ", "_")), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'ENTRETIEN BIS' introuvable"; return r
    try:
        df = xls.parse(sheet, header=2)
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    col_rt, col_statut, col_modele, col_mat, col_kms_notes = list(df.columns)[:5]
    palier_cols = {}
    for col in df.columns:
        try:
            v = int(float(str(col)))
            if v in PALIERS_KM_BIS: palier_cols[v] = col
        except: pass
    col_reste = next((c for c in df.columns if str(c).strip().upper() in ("REST", "RESTE")), None)

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_mat])
            if not plaque: continue
            raw = row[col_kms_notes]
            kms = _cf(raw)
            notes = None if kms is not None else (_cs(raw))
            paliers = {}
            for km in PALIERS_KM_BIS:
                col = palier_cols.get(km)
                paliers[str(km)] = _cf(row[col]) if col and not pd.isna(row[col]) else None
            vals = dict(
                rt=_cs(row[col_rt]), statut=_cs(row[col_statut]),
                modele=_cs(row[col_modele]), kms_depart=kms, notes=notes,
                paliers=paliers,
                reste=_cf(row[col_reste]) if col_reste and not pd.isna(row.get(col_reste)) else None,
            )
            existing = db.query(EntretienBis).filter_by(plaque_immatriculation=plaque).first()
            if existing:
                for k, v in vals.items(): setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(EntretienBis(plaque_immatriculation=plaque, **vals)); r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 4, "message": str(e)})
    db.commit()
    return r


def _pannes(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "PANNE" in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'SUIVI DES PANNE' introuvable"; return r
    try:
        df = xls.parse(sheet, header=0)
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    aliases = {
        "date": ["date"], "immatriculation": ["imma", "immatriculation", "plaque"],
        "nom": ["nom"], "garage": ["garage"],
        "nature_panne": ["nature", "panne", "non disponib"],
        "date_indisponibilite": ["indisponib", "date d'indispo"],
        "projet": ["projet"],
        "date_fin_reparation": ["fin de répa", "fin de repa", "date de fin"],
        "site": ["site"], "immobilisation_jrs": ["immobilisation", "immo", "jrs"],
        "commentaire": ["commentaire", "observation"],
    }
    col_map = {}
    for col in df.columns:
        cl = str(col).lower().strip()
        for field, keys in aliases.items():
            if field not in col_map and any(k in cl for k in keys):
                col_map[field] = col

    if "immatriculation" not in col_map:
        r.skipped = True; r.skip_reason = "Colonne IMMA introuvable"; return r

    def g(field): return col_map.get(field)

    for idx, row in df.iterrows():
        try:
            imma = _cs(row[g("immatriculation")]) if g("immatriculation") else None
            if not imma: continue
            date_val = _cd(row[g("date")]) if g("date") else None
            vals = dict(
                date=date_val, immatriculation=imma,
                nom=_cs(row[g("nom")]) if g("nom") else None,
                garage=_cs(row[g("garage")]) if g("garage") else None,
                nature_panne=_cs(row[g("nature_panne")]) if g("nature_panne") else None,
                date_indisponibilite=_cd(row[g("date_indisponibilite")]) if g("date_indisponibilite") else None,
                projet=_cs(row[g("projet")]) if g("projet") else None,
                date_fin_reparation=_cd(row[g("date_fin_reparation")]) if g("date_fin_reparation") else None,
                site=_cs(row[g("site")]) if g("site") else None,
                immobilisation_jrs=int(_cf(row[g("immobilisation_jrs")])) if g("immobilisation_jrs") and _cf(row[g("immobilisation_jrs")]) is not None else None,
                commentaire=_cs(row[g("commentaire")]) if g("commentaire") else None,
            )
            existing = db.query(SuiviPanne).filter_by(
                immatriculation=imma, date=date_val,
                nature_panne=vals["nature_panne"],
            ).first()
            if existing:
                for k, v in vals.items(): setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(SuiviPanne(**vals)); r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 2, "message": str(e)})
    db.commit()
    return r


def _pneumatiques(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    sheet = next((s for s in xls.sheet_names if "PNEUM" in s.upper()), None)
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'PNEUMATIQUE' introuvable"; return r
    try:
        df = xls.parse(sheet, header=None)
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    current_fournisseur = None
    col_map: dict[str, int] = {}

    def gs(v) -> str:
        if pd.isna(v): return ""
        s = str(v).strip()
        return "" if s.upper() in ("NAN", "N/A", "NA", "NONE") else s

    def gf_idx(vals_, ci):
        if ci >= len(vals_): return None
        v = vals_[ci]
        if pd.isna(v): return None
        try: return float(v)
        except: return None

    def gd_idx(vals_, ci):
        if ci >= len(vals_): return None
        v = vals_[ci]
        if pd.isna(v): return None
        try: return pd.to_datetime(v, dayfirst=True).date()
        except:
            try: return pd.to_datetime(str(v).strip(), dayfirst=True).date()
            except: return None

    for idx, row in df.iterrows():
        vals = [gs(v) for v in row.values]
        col_a = vals[0] if vals else ""
        col_c = vals[2] if len(vals) > 2 else ""

        if not any(vals): continue

        if not col_a:
            cand = col_c
            if cand and any(kw in cand.upper() for kw in SECTION_KEYWORDS_PNE):
                current_fournisseur = cand.strip()
                col_map = {}
            continue

        if col_a.upper() in ("IMMA", "IMMATRICULATION", "PLAQUE"):
            col_map = {}
            for ci, v in enumerate(vals):
                vu = v.upper()
                if any(k in vu for k in ("IMMA", "PLAQUE")): col_map["immatriculation"] = ci
                elif "CHAUFF" in vu: col_map["chauffeur"] = ci
                elif "KILOM" in vu: col_map["kilometrage"] = ci
                elif "N PNEU" in vu or (vu.startswith("N") and "PNEU" in vu): col_map["nb_pneus"] = ci
                elif "REF" in vu: col_map["ref_pneu"] = ci
                elif "ETAT" in vu: col_map["etat"] = ci
                elif "SNC" in vu: col_map["snc"] = ci
                elif "ZONE" in vu or "INTERVENTION" in vu or "FOOR" in vu: col_map["zone_intervention"] = ci
                elif "DATE" in vu and "PREV" in vu: col_map["date_prevue"] = ci
                elif "COMMENT" in vu: col_map["commentaire"] = ci
            continue

        if not col_a or col_a.upper() in ("NAT", "NAN", "N/A", "NA"):
            continue
        if "immatriculation" not in col_map:
            continue

        try:
            imma_ci = col_map["immatriculation"]
            imma = gs(row.values[imma_ci]) if imma_ci < len(row.values) else ""
            if not imma or imma.upper() in ("NAT", "NAN"): continue

            def get_s(field):
                ci = col_map.get(field)
                if ci is None: return None
                v = gs(row.values[ci]) if ci < len(row.values) else ""
                return v or None

            km_ci = col_map.get("kilometrage")
            row_km = None
            row_tl = None
            if km_ci is not None and km_ci < len(row.values):
                f = gf_idx(row.values, km_ci)
                if f is not None: row_km = f
                else:
                    s = gs(row.values[km_ci])
                    if s and any(kw in s.upper() for kw in TYPE_LOCATION_KEYWORDS):
                        row_tl = s

            nb = None
            if "nb_pneus" in col_map:
                v_nb = gf_idx(row.values, col_map["nb_pneus"])
                nb = int(v_nb) if v_nb is not None else None

            values = dict(
                fournisseur=current_fournisseur, type_location=row_tl,
                immatriculation=imma, chauffeur=get_s("chauffeur"),
                kilometrage=row_km, nb_pneus=nb,
                ref_pneu=get_s("ref_pneu"), etat=get_s("etat"),
                snc=get_s("snc"), zone_intervention=get_s("zone_intervention"),
                date_prevue=gd_idx(row.values, col_map["date_prevue"]) if "date_prevue" in col_map else None,
                commentaire=get_s("commentaire"),
            )
            existing = db.query(Pneumatique).filter_by(
                immatriculation=imma, fournisseur=current_fournisseur
            ).first()
            if existing:
                for k, v in values.items(): setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(Pneumatique(**values)); r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 1, "message": str(e)})

    db.commit()
    return r


# ── endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=ImportGlobalResult)
async def import_global(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    result = ImportGlobalResult(
        vehicules      = _vehicules(xls, db),
        couts          = _couts(xls, db),
        missions       = _missions(xls, db),
        devis          = _devis(xls, db),
        checklists     = _checklists(xls, db),
        entretiens     = _entretiens(xls, db),
        entretiens_bis = _entretiens_bis(xls, db),
        pannes         = _pannes(xls, db),
        pneumatiques   = _pneumatiques(xls, db),
    )

    # Persist history log
    results_dict = result.model_dump()
    sections = results_dict.values()
    log = ImportGlobalLog(
        username      = current_user.username if current_user else None,
        filename      = file.filename,
        results       = results_dict,
        total_created = sum(s["created"] for s in sections),
        total_updated = sum(s["updated"] for s in sections),
        total_errors  = sum(len(s["errors"]) for s in sections),
    )
    db.add(log)
    db.commit()

    return result


@router.get("/history", response_model=list[ImportGlobalLogOut])
def get_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    logs = (
        db.query(ImportGlobalLog)
        .order_by(ImportGlobalLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        ImportGlobalLogOut(
            id            = log.id,
            created_at    = log.created_at.isoformat(),
            username      = log.username,
            filename      = log.filename,
            total_created = log.total_created,
            total_updated = log.total_updated,
            total_errors  = log.total_errors,
            results       = log.results,
        )
        for log in logs
    ]
