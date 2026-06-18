import io
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..database import get_db
from ..models.suivi_sinistre import SuiviSinistre
from ..models.import_global_log import ImportGlobalLog
from ..models.user import User
from ..schemas.suivi_sinistre import SuiviSinistreCreate, SuiviSinistreUpdate, SuiviSinistreOut
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/sinistres", tags=["Sinistres"])


def _cd(v):
    if pd.isna(v): return None
    try:
        return pd.to_datetime(v, dayfirst=True).date()
    except Exception:
        return None


def _cs(v):
    if pd.isna(v): return None
    s = str(v).strip()
    return s if s and s.upper() not in ("NAN", "N/A", "NA", "NONE", "NAT", "00/00/000") else None


def _cf(v):
    if pd.isna(v): return None
    try:
        return float(v)
    except Exception:
        return None


@router.get("", response_model=dict)
def list_sinistres(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=10000),
    search: str = Query(""),
    statut: str = Query(""),
    type_location: str = Query(""),
    circonstances: str = Query(""),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(SuiviSinistre)
    if search:
        s = f"%{search}%"
        q = q.filter(or_(
            SuiviSinistre.matricule.ilike(s),
            SuiviSinistre.nom_chauffeur.ilike(s),
            SuiviSinistre.snc.ilike(s),
            SuiviSinistre.projet.ilike(s),
            SuiviSinistre.lieu_immobilisation.ilike(s),
        ))
    if statut:
        q = q.filter(SuiviSinistre.statut.ilike(f"%{statut}%"))
    if type_location:
        q = q.filter(SuiviSinistre.type_location.ilike(f"%{type_location}%"))
    if circonstances:
        q = q.filter(SuiviSinistre.circonstances.ilike(f"%{circonstances}%"))

    total = q.count()
    items = q.order_by(SuiviSinistre.date_sinistre.desc().nullslast(), SuiviSinistre.id.desc()) \
             .offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": [SuiviSinistreOut.model_validate(i) for i in items]}


@router.post("", response_model=SuiviSinistreOut)
def create_sinistre(body: SuiviSinistreCreate, db: Session = Depends(get_db), _=Depends(require_editor)):
    obj = SuiviSinistre(**body.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj


@router.put("/{sid}", response_model=SuiviSinistreOut)
def update_sinistre(sid: int, body: SuiviSinistreUpdate, db: Session = Depends(get_db), _=Depends(require_editor)):
    obj = db.query(SuiviSinistre).get(sid)
    if not obj: raise HTTPException(404, "Sinistre introuvable")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    db.commit(); db.refresh(obj)
    return obj


@router.delete("/{sid}")
def delete_sinistre(sid: int, db: Session = Depends(get_db), _=Depends(require_editor)):
    obj = db.query(SuiviSinistre).get(sid)
    if not obj: raise HTTPException(404, "Sinistre introuvable")
    db.delete(obj); db.commit()
    return {"ok": True}


@router.post("/import")
async def import_sinistres(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_editor)):
    content = await file.read()
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier Excel illisible")

    sheet = next((s for s in xls.sheet_names if "SUIVI" in s.upper() and "ASSUR" in s.upper()), None)
    if not sheet:
        sheet = next((s for s in xls.sheet_names if "SINISTRE" in s.upper()), None)
    if not sheet:
        raise HTTPException(400, "Feuille 'SUIVI DES ASSURANCES' introuvable")

    df = xls.parse(sheet, header=None)
    # Trouver la ligne d'en-tête (contient DATE DE SINISTRE)
    header_row = None
    for i, row in df.iterrows():
        vals = [str(v).upper() for v in row if not pd.isna(v)]
        if any("DATE DE SINISTRE" in v for v in vals):
            header_row = i
            break
    if header_row is None:
        raise HTTPException(400, "En-tête introuvable dans la feuille")

    df.columns = [str(df.iloc[header_row, c]).strip() for c in range(len(df.columns))]
    df = df.iloc[header_row + 1:].reset_index(drop=True)

    col = {str(c).upper(): c for c in df.columns}

    def gc(keys):
        for k in keys:
            for c in df.columns:
                if k in str(c).upper():
                    return c
        return None

    c_date_sin  = gc(["DATE DE SINISTRE"])
    c_date_decl = gc(["DATE DE DECLARATION"])
    c_type_loc  = gc(["LCD", "LLD", "CAMUSAT", "PROPRIETE"])
    c_matr      = gc(["MATRICULE"])
    c_nom       = gc(["NOM"])
    c_snc       = gc(["SNC"])
    c_projet    = gc(["PROJET"])
    c_circ      = gc(["CIRCONSTANCES"])
    c_statut    = gc(["STATUT"])
    c_montant   = gc(["MONTANT"])
    c_date_reg  = gc(["DATE DE REGLEMENT"])
    c_obs       = gc(["OBSERVATIONS"])
    c_suivi_par = gc(["DOSSIER SUIVI"])
    c_pos       = gc(["POSITION"])
    c_interne   = gc(["SUIVI DOSSIER"])
    c_lieu      = gc(["LIEU"])
    c_doc       = gc(["DOCUMENTATION"])
    c_traiter   = gc(["TRAITER"])

    created = updated = 0
    errors = []

    for idx, row in df.iterrows():
        matr = _cs(row[c_matr]) if c_matr else None
        if not matr:
            continue

        values = dict(
            date_sinistre         = _cd(row[c_date_sin]) if c_date_sin else None,
            date_declaration      = _cd(row[c_date_decl]) if c_date_decl else None,
            type_location         = _cs(row[c_type_loc]) if c_type_loc else None,
            matricule             = matr,
            nom_chauffeur         = _cs(row[c_nom]) if c_nom else None,
            snc                   = _cs(row[c_snc]) if c_snc else None,
            projet                = _cs(row[c_projet]) if c_projet else None,
            circonstances         = _cs(row[c_circ]) if c_circ else None,
            statut                = _cs(row[c_statut]) if c_statut else None,
            montant_indemnite     = _cf(row[c_montant]) if c_montant else None,
            date_reglement        = _cd(row[c_date_reg]) if c_date_reg else None,
            observations          = _cs(row[c_obs]) if c_obs else None,
            dossier_suivi_par     = _cs(row[c_suivi_par]) if c_suivi_par else None,
            position_vehicule     = _cs(row[c_pos]) if c_pos else None,
            suivi_dossier_interne = _cs(row[c_interne]) if c_interne else None,
            lieu_immobilisation   = _cs(row[c_lieu]) if c_lieu else None,
            documentation         = bool(int(_cf(row[c_doc]))) if c_doc and _cf(row[c_doc]) is not None else None,
            traiter               = bool(int(_cf(row[c_traiter]))) if c_traiter and _cf(row[c_traiter]) is not None else None,
        )

        try:
            existing = db.query(SuiviSinistre).filter(
                SuiviSinistre.matricule == matr,
                SuiviSinistre.date_declaration == values["date_declaration"],
                SuiviSinistre.circonstances == values["circonstances"],
            ).first()
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(SuiviSinistre(**values))
                created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 1, "message": str(e)})

    db.commit()

    # Sauvegarder dans l'historique des imports
    log = ImportGlobalLog(
        username      = current_user.username if current_user else None,
        filename      = file.filename,
        results       = {"sinistres": {"created": created, "updated": updated, "errors": errors, "skipped": False, "skip_reason": ""}},
        total_created = created,
        total_updated = updated,
        total_errors  = len(errors),
    )
    db.add(log)
    db.commit()

    return {"created": created, "updated": updated, "errors": errors}
