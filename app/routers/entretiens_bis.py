import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.entretien_bis import EntretienBis
from ..schemas.entretien_bis import EntretienBisOut, EntretienBisCreate, EntretienBisUpdate, ImportEntretienBisResult
from ..services.auth_service import get_current_user, require_editor

router = APIRouter(prefix="/api/entretiens-bis", tags=["Flotte — Entretiens BIS"])

# Paliers kilométriques du contrat BIS — feuille ENTRETIEN BIS (12 paliers réels)
PALIERS_KM_BIS = [
    112500, 120000, 135000, 142500, 150000,
    157500, 165000, 172500, 180000, 187500, 195000, 202500,
]


@router.get("/paliers", response_model=list[int])
def list_paliers(_: User = Depends(get_current_user)):
    return PALIERS_KM_BIS


@router.post("/auto-calculer", response_model=list[EntretienBisOut])
def auto_calculer(
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    """
    Pour chaque véhicule BIS ayant un kms_depart renseigné,
    recalcule automatiquement les paliers franchis et le 'reste' km.
    - Palier franchi (kms_depart >= km_palier) : conserve la valeur existante ou marque kms_depart
    - Prochain palier : premier palier > kms_depart → reste = palier - kms_depart
    """
    entretiens = db.query(EntretienBis).all()
    updated = []
    for e in entretiens:
        if e.kms_depart is None:
            continue
        kms = float(e.kms_depart)
        paliers = dict(e.paliers or {})

        # Marquer les paliers franchis sans valeur existante
        prochain_palier = None
        for km in PALIERS_KM_BIS:
            key = str(km)
            if kms >= km:
                if paliers.get(key) is None:
                    paliers[key] = kms
            else:
                if prochain_palier is None:
                    prochain_palier = km

        reste = (prochain_palier - kms) if prochain_palier is not None else None
        e.paliers = paliers
        e.reste = reste
        updated.append(e)

    if updated:
        db.commit()
        for e in updated:
            db.refresh(e)

    return db.query(EntretienBis).order_by(EntretienBis.plaque_immatriculation).all()


@router.get("", response_model=list[EntretienBisOut])
def list_entretiens_bis(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(EntretienBis).order_by(EntretienBis.plaque_immatriculation).all()


@router.post("", response_model=EntretienBisOut, status_code=201)
def create_entretien_bis(
    data: EntretienBisCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    if db.query(EntretienBis).filter(EntretienBis.plaque_immatriculation == data.plaque_immatriculation).first():
        raise HTTPException(400, "Un suivi BIS existe déjà pour cette plaque")
    entretien = EntretienBis(**data.model_dump())
    db.add(entretien); db.commit(); db.refresh(entretien)
    return entretien


@router.patch("/{entretien_id}", response_model=EntretienBisOut)
def update_entretien_bis(
    entretien_id: int,
    data: EntretienBisUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    entretien = db.query(EntretienBis).filter(EntretienBis.id == entretien_id).first()
    if not entretien:
        raise HTTPException(404, "Suivi BIS introuvable")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entretien, key, value)
    db.commit(); db.refresh(entretien)
    return entretien


@router.delete("/{entretien_id}", status_code=204)
def delete_entretien_bis(
    entretien_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_editor),
):
    entretien = db.query(EntretienBis).filter(EntretienBis.id == entretien_id).first()
    if not entretien:
        raise HTTPException(404, "Suivi BIS introuvable")
    db.delete(entretien); db.commit()


@router.post("/import", response_model=ImportEntretienBisResult)
async def import_entretiens_bis(
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
        (s for s in xls.sheet_names if "ENTRETIEN BIS" in s.upper() or "ENTRETIEN_BIS" in s.upper().replace(" ", "_")),
        None
    )
    if not sheet_name:
        raise HTTPException(400, "Feuille 'ENTRETIEN BIS' introuvable dans le fichier")

    # Ligne 3 = en-têtes (header=2). Structure réelle :
    # [RT, STATUT, MODEL, Matricule, KMS DE DEPART NOTES, 112500…202500, Unnamed:17, Unnamed:18, REST]
    # KMS DE DEPART et NOTES sont fusionnés en une seule colonne : valeur numérique = km, texte = notes
    df = xls.parse(sheet_name, header=2)
    str_cols = [str(c) for c in df.columns]

    # Colonnes fixes
    col_rt       = df.columns[0]
    col_statut   = df.columns[1]
    col_modele   = df.columns[2]
    col_matricule = df.columns[3]
    col_kms_notes = df.columns[4]  # colonne fusionnée KMS DE DEPART / NOTES

    # Paliers : colonnes dont la valeur numérique correspond exactement aux paliers attendus
    palier_cols = {}  # km_int -> column_name
    for col in df.columns:
        try:
            v = int(float(str(col)))
            if v in PALIERS_KM_BIS:
                palier_cols[v] = col
        except (ValueError, TypeError):
            pass

    # REST : chercher par nom de colonne (insensible à la casse)
    col_reste = next(
        (c for c in df.columns if str(c).strip().upper() in ("REST", "RESTE")),
        None
    )

    created = 0
    updated = 0
    errors = []

    def clean_str(v):
        return None if pd.isna(v) else str(v).strip() or None

    def clean_num(v):
        try:
            f = float(v)
            return None if pd.isna(f) else f
        except (TypeError, ValueError):
            return None

    for idx, row in df.iterrows():
        try:
            plaque = row[col_matricule]
            if pd.isna(plaque) or not str(plaque).strip():
                continue
            plaque = str(plaque).strip()

            # Colonne fusionnée : numérique → kms_depart, texte → notes
            raw_kms_notes = row[col_kms_notes]
            kms_depart_val = clean_num(raw_kms_notes)
            notes_val = None
            if kms_depart_val is None and not pd.isna(raw_kms_notes):
                txt = str(raw_kms_notes).strip()
                if txt:
                    notes_val = txt

            # Paliers lus depuis le fichier
            paliers: dict = {}
            for km in PALIERS_KM_BIS:
                col = palier_cols.get(km)
                paliers[str(km)] = clean_num(row[col]) if col is not None else None

            # Reste
            reste_val = clean_num(row[col_reste]) if col_reste is not None else None

            # Auto-compléter les paliers et le reste si kms_depart est renseigné
            if kms_depart_val is not None:
                for km in PALIERS_KM_BIS:
                    key = str(km)
                    if paliers.get(key) is None and kms_depart_val >= km:
                        paliers[key] = kms_depart_val
                if reste_val is None:
                    prochain = next((km for km in PALIERS_KM_BIS if km > kms_depart_val), None)
                    reste_val = (prochain - kms_depart_val) if prochain is not None else None

            existing = db.query(EntretienBis).filter_by(plaque_immatriculation=plaque).first()
            values = dict(
                rt=clean_str(row[col_rt]),
                statut=clean_str(row[col_statut]),
                modele=clean_str(row[col_modele]),
                kms_depart=kms_depart_val,
                notes=notes_val,
                paliers=paliers,
                reste=reste_val,
            )
            if existing:
                for k, v in values.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(EntretienBis(plaque_immatriculation=plaque, **values))
                created += 1
        except Exception as e:
            errors.append({"ligne": int(idx) + 4, "message": str(e)})

    db.commit()
    return ImportEntretienBisResult(created=created, updated=updated, errors=errors)
