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
from ..models.suivi_sinistre import SuiviSinistre
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
    sinistres: SectionResult = SectionResult(skipped=True, skip_reason="Fichier sinistres non fourni")


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


def _find_col(columns: list[str], *keywords: str) -> str | None:
    """Trouve la première colonne dont le nom contient l'un des mots-clés (insensible à la casse)."""
    for kw in keywords:
        for c in columns:
            if kw.upper() in str(c).upper():
                return c
    return None


def _parse_sheet(xls: pd.ExcelFile, *name_fragments: str, header: int = 0) -> tuple[pd.DataFrame | None, str]:
    """Parse une feuille identifiée par des fragments de nom. Retourne (df, erreur)."""
    sheet = next(
        (s for s in xls.sheet_names
         if all(f.upper() in s.upper() for f in name_fragments)),
        None
    )
    if not sheet:
        return None, f"Feuille contenant {name_fragments} introuvable"
    try:
        df = xls.parse(sheet, header=header)
        df.columns = [" ".join(str(c).split()) for c in df.columns]
        return df, ""
    except Exception as e:
        return None, str(e)


# ── parsers ──────────────────────────────────────────────────────────────────

def _vehicules(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    df, err = _parse_sheet(xls, "FLOTTE GLOBALE")
    if df is None:
        r.skipped = True; r.skip_reason = err; return r

    col_plaque = _find_col(list(df.columns), "PLAQUE", "IMMATRICULATION")
    if not col_plaque:
        r.skipped = True; r.skip_reason = "Colonne plaque introuvable"; return r

    cols = list(df.columns)
    col_map = {
        "type_location":   _find_col(cols, "TYPE DE LOCATION", "TYPE DE LOCAT"),
        "fournisseur":     _find_col(cols, "FOURNISSEUR"),
        "type_vehicule":   _find_col(cols, "TYPE VEHICULE", "TYPE VÉ"),
        "n_chassis":       _find_col(cols, "CHASSIS"),
        "modele":          _find_col(cols, "MODEL"),
        "couleur":         _find_col(cols, "COULEUR"),
        "autocollant":     _find_col(cols, "AUTOCOL"),
        "extincteurs":     _find_col(cols, "EXTINC"),
        "trousse_secours": _find_col(cols, "TROUSSE"),
        "carte_carburant": _find_col(cols, "CARTE", "CARB"),
    }

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_plaque])
            if not plaque:
                continue
            vals = {k: _cs(row[v]) if v and not pd.isna(row.get(v, float("nan"))) else None
                    for k, v in col_map.items() if v}
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
    df, err = _parse_sheet(xls, "DATA_FLOTTE")
    if df is None:
        r.skipped = True; r.skip_reason = err; return r

    cols = list(df.columns)
    col_plaque   = _find_col(cols, "PLAQUE", "IMMATRICULATION")
    col_mois     = _find_col(cols, "MOIS")
    col_type     = _find_col(cols, "TYPE_COUT", "TYPE COUT")
    col_valeur   = _find_col(cols, "VALEUR")
    col_tl       = _find_col(cols, "TYPE DE LOCATION", "TYPE DE LOCAT")
    col_fourn    = _find_col(cols, "FOURNISSEUR")
    col_tv       = _find_col(cols, "TYPE VEHICULE")

    if not all([col_plaque, col_mois, col_type, col_valeur]):
        r.skipped = True
        r.skip_reason = f"Colonnes manquantes parmi : plaque={col_plaque}, mois={col_mois}, type={col_type}, valeur={col_valeur}"
        return r

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_plaque])
            mois_val = row[col_mois]
            type_cout_val = row[col_type]
            if not plaque or pd.isna(mois_val) or pd.isna(type_cout_val):
                continue
            mois: DateType = pd.to_datetime(mois_val).date().replace(day=1)
            type_cout = str(type_cout_val).strip().upper()
            valeur = float(row[col_valeur]) if not pd.isna(row[col_valeur]) else 0.0
            type_location = _cs(row[col_tl]) if col_tl else None
            fournisseur   = _cs(row[col_fourn]) if col_fourn else None
            type_vehicule = _cs(row[col_tv]) if col_tv else None
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
    df, err = _parse_sheet(xls, "CHAUFFEUR", "POLE", header=1)
    if df is None:
        r.skipped = True; r.skip_reason = err; return r

    cols = list(df.columns)
    col_date  = _find_col(cols, "DATE")
    col_imma  = _find_col(cols, "IMMA", "IMMATRICULATION")
    if not col_date or not col_imma:
        r.skipped = True; r.skip_reason = f"Colonnes manquantes : date={col_date}, imma={col_imma}"; return r

    def pd_(v) -> DateType | None:
        if pd.isna(v): return None
        try: return pd.to_datetime(v).date()
        except: return None

    for idx, row in df.iterrows():
        try:
            mission_date = pd_(row[col_date])
            imma = _cs(row[col_imma])
            if not mission_date or not imma:
                continue
            col_chauf = _find_col(cols, "CHAUFFEUR")
            col_dem   = _find_col(cols, "DEMANDEUR")
            col_tel   = _find_col(cols, "TELEPHONE", "TEL")
            col_proj  = _find_col(cols, "PROJET")
            col_dest  = _find_col(cols, "DESTINATION")
            col_dep   = _find_col(cols, "DEPART")
            col_ret   = _find_col(cols, "RETOUR")
            col_com   = _find_col(cols, "COMMENTAIRE")
            vals = dict(
                date=mission_date, immatriculation=imma,
                chauffeur=_cs(row[col_chauf]) if col_chauf else None,
                demandeur=_cs(row[col_dem]) if col_dem else None,
                telephone=_cs(row[col_tel]) if col_tel else None,
                projet=_cs(row[col_proj]) if col_proj else None,
                destination=_cs(row[col_dest]) if col_dest else None,
                date_depart=pd_(row[col_dep]) if col_dep else None,
                date_retour=pd_(row[col_ret]) if col_ret else None,
                commentaires=_cs(row[col_com]) if col_com else None,
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

    # Essayer plusieurs valeurs de header pour trouver la bonne ligne
    sheet_name = next(
        (s for s in xls.sheet_names if "SUIVI" in s.upper() and "DEVIS" in s.upper()), None
    )
    if not sheet_name:
        r.skipped = True; r.skip_reason = "Feuille 'SUIVI DES DEVIS' introuvable"; return r

    df = None
    for h in range(0, 8):
        try:
            candidate = xls.parse(sheet_name, header=h)
            candidate.columns = [" ".join(str(c).split()) for c in candidate.columns]
            # La bonne ligne header contient "DESCRIPTION" ou "DEVIS"
            if any("DESCRIPTION" in str(c).upper() or "DEVIS" in str(c).upper() for c in candidate.columns):
                df = candidate
                break
        except Exception:
            continue

    if df is None:
        r.skipped = True; r.skip_reason = "Impossible de détecter la ligne d'en-tête SUIVI DES DEVIS"; return r

    cols = list(df.columns)
    col_map = {
        "descriptions":  _find_col(cols, "DESCRIPTION"),
        "numero_devis":  _find_col(cols, "N° DEVIS", "N°DEVIS", "# DEVIS", "DEVIS"),
        "valeur_devis":  _find_col(cols, "VALEUR DEVIS", "VALEUR"),
        "date":          next((c for c in cols if c.strip().upper() == "DATE"), None),
        "montant":       next((c for c in cols if c.strip().upper() in ("MONTANT", "MONTANT (FCFA)")), None),
        "sous_traitant": _find_col(cols, "SOUS-TRAIT", "SUPPLIER", "SOUS_TRAIT"),
        "matricule":     next((c for c in cols if c.strip().upper() == "MATRICULE"), None),
        "code_snc":      _find_col(cols, "CODE SNC"),
        "po_emis":       _find_col(cols, "PO EMIS", "PO"),
    }

    def pd_(v) -> DateType | None:
        if pd.isna(v): return None
        if isinstance(v, (pd.Timestamp, datetime)): return v.date()
        try: return pd.to_datetime(v, dayfirst=True).date()
        except: return None

    col_desc = col_map["descriptions"]
    if not col_desc:
        r.skipped = True; r.skip_reason = "Colonne DESCRIPTIONS introuvable"; return r

    for idx, row in df.iterrows():
        try:
            desc = _cs(row[col_desc])
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
                descriptions=desc, numero_devis=vals["numero_devis"],
            ).first()
            if existing:
                for k, v in vals.items(): setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(SuiviDevis(**vals)); r.created += 1
        except Exception as e:
            r.errors.append({"ligne": int(idx) + 2, "message": str(e)})
    db.commit()
    return r


def _checklists(xls: pd.ExcelFile, db: Session) -> SectionResult:
    r = SectionResult()
    df, err = _parse_sheet(xls, "CHECK", "LIST", header=1)
    if df is None:
        r.skipped = True; r.skip_reason = err; return r

    cols = list(df.columns)
    col_plaque = _find_col(cols, "REG", "PLAQUE", "IMMA")
    if not col_plaque:
        r.skipped = True; r.skip_reason = "Colonne plaque introuvable"; return r

    fixed = {_find_col(cols, "BRAND"), _find_col(cols, "MODEL"), col_plaque,
             _find_col(cols, "LABEL"), _find_col(cols, "CAR GROUP"), None}
    semaine_cols = [c for c in cols if c not in fixed and str(c).strip()]

    seen: dict[str, CheckListVL] = {}
    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_plaque])
            if not plaque: continue
            semaines = {s: _cs(row[s]) for s in semaine_cols}
            vals = dict(
                brand=_cs(row.get(_find_col(cols, "BRAND") or "")),
                model=_cs(row.get(_find_col(cols, "MODEL") or "")),
                label=_cs(row.get(_find_col(cols, "LABEL") or "")),
                car_group=_cs(row.get(_find_col(cols, "CAR GROUP") or "")),
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
    df, err = _parse_sheet(xls, "ENTRTIEN", header=2)
    if df is None:
        # Essayer aussi "ENTRETIEN" sans le BIS
        sheet = next(
            (s for s in xls.sheet_names
             if "ENTRETIEN" in s.upper().replace("_", " ") and "BIS" not in s.upper()),
            None
        )
        if not sheet:
            r.skipped = True; r.skip_reason = "Feuille ENTRTIENS introuvable"; return r
        try:
            df = xls.parse(sheet, header=2)
            df.columns = [" ".join(str(c).split()) for c in df.columns]
        except Exception as e:
            r.skipped = True; r.skip_reason = str(e); return r

    cols = list(df.columns)
    if len(cols) < 5:
        r.skipped = True; r.skip_reason = f"Trop peu de colonnes ({len(cols)}) dans ENTRTIENS"; return r

    # Identifier les colonnes par nom
    col_tl  = _find_col(cols, "TYPE DE LOCATION", "TYPE LOCATION", "TYPE LOC")
    col_f   = _find_col(cols, "FOURNISSEUR")
    col_tv  = _find_col(cols, "TYPE VEHICULE", "TYPE VEH")
    col_mat = _find_col(cols, "MATRICULE", "PLAQUE", "IMMA")
    col_nom = _find_col(cols, "NOM", "CHAUFFEUR")

    # Fallback positionnel si les noms ne matchent pas
    if not col_mat:
        col_tl, col_f, col_tv, col_mat, col_nom = cols[0], cols[1], cols[2], cols[3], cols[4]

    # Colonnes paliers = colonnes dont le nom est un nombre entier
    palier_cols: dict[int, str] = {}
    for c in cols:
        try:
            km = int(float(str(c).replace(" ", "")))
            if km in PALIERS_KM:
                palier_cols[km] = c
        except (ValueError, TypeError):
            pass

    # Si pas de colonne palier trouvée, utiliser les colonnes positionnelles
    if not palier_cols:
        fixed_cols = {col_tl, col_f, col_tv, col_mat, col_nom}
        remaining = [c for c in cols if c not in fixed_cols]
        for i, km in enumerate(PALIERS_KM):
            if i < len(remaining):
                palier_cols[km] = remaining[i]

    col_reste = _find_col(cols, "REST")

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_mat]) if col_mat else None
            if not plaque: continue
            paliers = {
                str(km): (_cf(row[col]) if not pd.isna(row[col]) else None)
                for km, col in palier_cols.items()
            }
            vals = dict(
                type_location=_cs(row[col_tl]) if col_tl else None,
                fournisseur=_cs(row[col_f]) if col_f else None,
                type_vehicule=_cs(row[col_tv]) if col_tv else None,
                nom_chauffeur=_cs(row[col_nom]) if col_nom else None,
                paliers=paliers,
                reste=_cf(row[col_reste]) if col_reste and not pd.isna(row.get(col_reste, float("nan"))) else None,
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
    sheet = next(
        (s for s in xls.sheet_names if "BIS" in s.upper() and "ENTRETIEN" in s.upper().replace("_", " ")),
        None
    )
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille 'ENTRETIEN BIS' introuvable"; return r

    try:
        df = xls.parse(sheet, header=2)
        df.columns = [" ".join(str(c).split()) for c in df.columns]
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    cols = list(df.columns)
    if len(cols) < 4:
        r.skipped = True; r.skip_reason = f"Trop peu de colonnes ({len(cols)}) dans ENTRETIEN BIS"; return r

    # Identification par nom, fallback positionnel
    col_rt     = _find_col(cols, "RT") or cols[0]
    col_statut = _find_col(cols, "STATUT") or (cols[1] if len(cols) > 1 else None)
    col_modele = _find_col(cols, "MODEL", "MODELE") or (cols[2] if len(cols) > 2 else None)
    col_mat    = _find_col(cols, "MATRICULE", "PLAQUE", "IMMA") or (cols[3] if len(cols) > 3 else None)
    col_kms    = _find_col(cols, "KMS", "KILOMETRAGE", "NOTES") or (cols[4] if len(cols) > 4 else None)

    palier_cols: dict[int, str] = {}
    for c in cols:
        try:
            km = int(float(str(c).replace(" ", "")))
            if km in PALIERS_KM_BIS:
                palier_cols[km] = c
        except (ValueError, TypeError):
            pass

    # Fallback positionnel pour les paliers
    if not palier_cols:
        fixed = {col_rt, col_statut, col_modele, col_mat, col_kms}
        remaining = [c for c in cols if c not in fixed]
        for i, km in enumerate(PALIERS_KM_BIS):
            if i < len(remaining):
                palier_cols[km] = remaining[i]

    col_reste = _find_col(cols, "REST")

    for idx, row in df.iterrows():
        try:
            plaque = _cs(row[col_mat]) if col_mat else None
            if not plaque: continue
            raw = row[col_kms] if col_kms else None
            kms = _cf(raw) if raw is not None else None
            notes = None if kms is not None else _cs(raw)
            paliers = {
                str(km): (_cf(row[col]) if col in df.columns and not pd.isna(row.get(col, float("nan"))) else None)
                for km, col in palier_cols.items()
            }
            vals = dict(
                rt=_cs(row[col_rt]) if col_rt else None,
                statut=_cs(row[col_statut]) if col_statut else None,
                modele=_cs(row[col_modele]) if col_modele else None,
                kms_depart=kms, notes=notes,
                paliers=paliers,
                reste=_cf(row[col_reste]) if col_reste and not pd.isna(row.get(col_reste, float("nan"))) else None,
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
    df, err = _parse_sheet(xls, "PANNE")
    if df is None:
        r.skipped = True; r.skip_reason = err; return r

    cols = list(df.columns)
    col_imma    = _find_col(cols, "IMMA", "IMMATRICULATION", "PLAQUE")
    col_date    = _find_col(cols, "DATE")
    col_nom     = _find_col(cols, "NOM")
    col_garage  = _find_col(cols, "GARAGE")
    col_nature  = _find_col(cols, "NATURE", "PANNE", "NON DISPONIB", "INDISPONIB")
    col_dindispo = _find_col(cols, "INDISPONIB", "DATE D'INDISPO")
    col_projet  = _find_col(cols, "PROJET")
    col_fin_rep = _find_col(cols, "FIN DE RÉP", "FIN DE REP", "DATE DE FIN")
    col_site    = _find_col(cols, "SITE")
    col_immo    = _find_col(cols, "IMMOBILISATION", "IMMO", "JRS")
    col_com     = _find_col(cols, "COMMENTAIRE", "OBSERVATION")

    if not col_imma:
        r.skipped = True; r.skip_reason = "Colonne IMMA introuvable"; return r

    for idx, row in df.iterrows():
        try:
            imma = _cs(row[col_imma])
            if not imma: continue
            date_val = _cd(row[col_date]) if col_date else None
            nature   = _cs(row[col_nature]) if col_nature else None
            immo_raw = _cf(row[col_immo]) if col_immo else None
            vals = dict(
                date=date_val, immatriculation=imma,
                nom=_cs(row[col_nom]) if col_nom else None,
                garage=_cs(row[col_garage]) if col_garage else None,
                nature_panne=nature,
                date_indisponibilite=_cd(row[col_dindispo]) if col_dindispo else None,
                projet=_cs(row[col_projet]) if col_projet else None,
                date_fin_reparation=_cd(row[col_fin_rep]) if col_fin_rep else None,
                site=_cs(row[col_site]) if col_site else None,
                immobilisation_jrs=int(immo_raw) if immo_raw is not None else None,
                commentaire=_cs(row[col_com]) if col_com else None,
            )
            existing = db.query(SuiviPanne).filter_by(
                immatriculation=imma, date=date_val, nature_panne=nature,
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


def _sinistres(xls: pd.ExcelFile, db: Session) -> SectionResult:
    """Parse le fichier ETAT SUIVI DES SINISTRES (feuille DONNEES)."""
    r = SectionResult()
    # Cherche la feuille par "DONNEES" ou "SINISTRE"
    sheet = next(
        (s for s in xls.sheet_names
         if "DONNEE" in s.upper() or "SINISTRE" in s.upper()),
        None
    )
    if not sheet:
        r.skipped = True; r.skip_reason = "Feuille DONNEES/SINISTRES introuvable"; return r

    try:
        df = xls.parse(sheet, header=0)
        df.columns = [" ".join(str(c).split()) for c in df.columns]
    except Exception as e:
        r.skipped = True; r.skip_reason = str(e); return r

    cols = list(df.columns)
    col_mat      = _find_col(cols, "MATRICULE")
    col_date_dec = _find_col(cols, "DATE DE DECLAR", "DATE DECLAR", "DECLARATION")
    col_type     = _find_col(cols, "PROPRIETE", "TYPE LOCATION", "TYPE_LOCATION")
    col_snc      = _find_col(cols, "SNC")
    col_projet   = _find_col(cols, "PROJET")
    col_circ     = _find_col(cols, "CIRCONSTANCE")
    col_doc      = _find_col(cols, "DOCUMENTATION")
    col_traiter  = _find_col(cols, "TRAITER")
    col_statut   = _find_col(cols, "STATUT")
    col_pos_veh  = _find_col(cols, "POSITION VEHICULE", "POSITION")
    col_lieu     = _find_col(cols, "LIEU IMMOBILI", "LIEU")
    col_obs      = _find_col(cols, "OBSERVATION")
    col_chauff   = _find_col(cols, "NOM CHAUFFEUR", "CHAUFFEUR", "NOM")
    col_montant  = _find_col(cols, "MONTANT", "INDEMNI")
    col_date_sin = _find_col(cols, "DATE SINISTRE", "DATE SIN")

    if not col_mat:
        r.skipped = True; r.skip_reason = "Colonne MATRICULE introuvable"; return r

    for idx, row in df.iterrows():
        try:
            matricule = _cs(row[col_mat])
            if not matricule:
                continue
            vals = dict(
                matricule=matricule,
                date_sinistre=_cd(row[col_date_sin]) if col_date_sin else None,
                date_declaration=_cd(row[col_date_dec]) if col_date_dec else None,
                type_location=_cs(row[col_type]) if col_type else None,
                nom_chauffeur=_cs(row[col_chauff]) if col_chauff else None,
                snc=_cs(row[col_snc]) if col_snc else None,
                projet=_cs(row[col_projet]) if col_projet else None,
                circonstances=_cs(row[col_circ]) if col_circ else None,
                documentation=bool(int(row[col_doc])) if col_doc and not pd.isna(row.get(col_doc, float("nan"))) else False,
                traiter=bool(int(row[col_traiter])) if col_traiter and not pd.isna(row.get(col_traiter, float("nan"))) else False,
                statut=_cs(row[col_statut]) if col_statut else None,
                position_vehicule=_cs(row[col_pos_veh]) if col_pos_veh else None,
                lieu_immobilisation=_cs(row[col_lieu]) if col_lieu else None,
                observations=_cs(row[col_obs]) if col_obs else None,
                montant_indemnite=_cf(row[col_montant]) if col_montant else None,
            )
            existing = db.query(SuiviSinistre).filter_by(
                matricule=matricule,
                date_declaration=vals["date_declaration"],
                circonstances=vals["circonstances"],
            ).first()
            if existing:
                for k, v in vals.items():
                    setattr(existing, k, v)
                r.updated += 1
            else:
                db.add(SuiviSinistre(**vals))
                r.created += 1
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
        if ci is None or ci >= len(vals_): return None
        v = vals_[ci]
        if pd.isna(v): return None
        try: return float(v)
        except: return None

    def gd_idx(vals_, ci):
        if ci is None or ci >= len(vals_): return None
        v = vals_[ci]
        if pd.isna(v): return None
        try: return pd.to_datetime(v, dayfirst=True).date()
        except:
            try: return pd.to_datetime(str(v).strip(), dayfirst=True).date()
            except: return None

    for idx, row in df.iterrows():
        try:
            vals = [gs(v) for v in row.values]
            col_a = vals[0] if vals else ""
            col_c = vals[2] if len(vals) > 2 else ""

            if not any(vals): continue

            if not col_a:
                if col_c and any(kw in col_c.upper() for kw in SECTION_KEYWORDS_PNE):
                    current_fournisseur = col_c.strip()
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

            nb_raw = gf_idx(row.values, col_map.get("nb_pneus"))
            nb = int(nb_raw) if nb_raw is not None else None

            values = dict(
                fournisseur=current_fournisseur, type_location=row_tl,
                immatriculation=imma, chauffeur=get_s("chauffeur"),
                kilometrage=row_km, nb_pneus=nb,
                ref_pneu=get_s("ref_pneu"), etat=get_s("etat"),
                snc=get_s("snc"), zone_intervention=get_s("zone_intervention"),
                date_prevue=gd_idx(row.values, col_map.get("date_prevue")),
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
    sinistres_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_editor),
):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sin_result = SectionResult(skipped=True, skip_reason="Fichier sinistres non fourni")
    if sinistres_file:
        sin_content = await sinistres_file.read()
        try:
            xls_sin = pd.ExcelFile(io.BytesIO(sin_content))
            sin_result = _sinistres(xls_sin, db)
        except Exception as e:
            sin_result = SectionResult(skipped=True, skip_reason=f"Fichier sinistres illisible : {e}")

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
        sinistres      = sin_result,
    )

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


@router.delete("/clear-all")
def clear_all_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_editor),
):
    """Supprime toutes les données métier (hors utilisateurs et logs)."""
    counts = {}
    for Model, label in [
        (CoutFlotte,       "couts_flotte"),
        (MissionChauffeur, "missions_chauffeur"),
        (SuiviDevis,       "suivi_devis"),
        (CheckListVL,      "checklists_vl"),
        (EntretienVehicule,"entretiens"),
        (EntretienBis,     "entretiens_bis"),
        (SuiviPanne,       "suivi_pannes"),
        (Pneumatique,      "pneumatiques"),
        (SuiviSinistre,    "suivi_sinistres"),
        (Vehicule,         "vehicules"),
        (ImportGlobalLog,  "import_logs"),
    ]:
        n = db.query(Model).delete(synchronize_session=False)
        counts[label] = n
    db.commit()
    return {"deleted": counts, "message": "Toutes les données ont été supprimées."}
