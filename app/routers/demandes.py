"""
Demandes des chauffeurs (app mobile) : remontée, panne, vidange.
Chaque nouvelle demande déclenche une alerte e-mail (DEMANDES_EMAIL_ALERTE) ; la plateforme
les liste, les compte (cloche de notification) et en suit le traitement.
"""
import html
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models.demande import NATURES_DEMANDE, STATUTS_DEMANDE, DemandeVehicule
from ..models.user import User
from ..services.auth_service import get_current_user, require_chauffeur, require_editor
from ..services.email import ErreurEmail, envoyer_email
from ..services.notifications import envoyer_push, notifier

router = APIRouter(prefix="/api/demandes", tags=["Demandes chauffeurs"])
log = logging.getLogger("eflotte.demandes")


# ── Schémas ────────────────────────────────────────────────────────────────

class DemandeIn(BaseModel):
    nature: str
    immatriculation: str = Field(min_length=1, max_length=30)
    kilometrage: int = Field(ge=0, le=5_000_000)
    position: str = Field(min_length=1, max_length=255)
    technicien: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)   # « Nature » : explication libre


class DemandeOut(BaseModel):
    id: int
    user_id: int | None
    nature: str
    immatriculation: str
    kilometrage: int
    position: str
    technicien: str
    description: str | None
    nom_chauffeur: str
    telephone: str | None
    statut: str
    commentaire: str | None
    traitee_par: str | None
    email_alerte_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    model_config = {"from_attributes": True}


class DemandePage(BaseModel):
    items: list[DemandeOut]
    total: int


class DemandeMaj(BaseModel):
    statut: str
    commentaire: str | None = None


# ── Alerte e-mail ──────────────────────────────────────────────────────────

def _alerter_par_email(demande_id: int) -> None:
    """Tâche de fond : e-mail aux responsables pour une nouvelle demande."""
    db = SessionLocal()
    try:
        d = db.get(DemandeVehicule, demande_id)
        if not d:
            return
        nature = NATURES_DEMANDE.get(d.nature, d.nature)
        lien = (settings.app_url.rstrip("/") + "/demandes") if settings.app_url else ""
        sujet = f"eFlotte : nouvelle demande {nature.lower()} — {d.immatriculation}"
        lignes = [
            ("Type", nature), ("Nature", d.description or "—"), ("Immatriculation", d.immatriculation),
            ("Kilométrage actuel", f"{d.kilometrage:,} km".replace(",", " ")),
            ("Position", d.position), ("Technicien", d.technicien),
            ("Chauffeur", d.nom_chauffeur + (f" ({d.telephone})" if d.telephone else "")),
            ("Reçue le", d.created_at.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC") if d.created_at else ""),
        ]
        texte = "Nouvelle demande reçue depuis l'application mobile eFlotte.\n\n" + \
            "\n".join(f"{k} : {v}" for k, v in lignes) + (f"\n\nVoir les demandes : {lien}" if lien else "")
        e = html.escape
        lignes_html = "".join(
            f'<tr><td style="padding:4px 14px 4px 0;color:#6b7280">{e(k)}</td><td style="font-weight:bold">{e(str(v))}</td></tr>'
            for k, v in lignes)
        bouton = (f'<p><a href="{e(lien)}" style="background:#0f3b82;color:#fff;padding:10px 16px;border-radius:10px;'
                  f'text-decoration:none;font-weight:bold">Voir les demandes</a></p>') if lien else ""
        contenu_html = f"""<div style="font-family:Arial,sans-serif;max-width:560px;color:#0b1f44">
  <h2 style="color:#0f3b82;margin:0 0 8px">Nouvelle demande : {e(nature)}</h2>
  <p>Reçue depuis l'application mobile eFlotte.</p>
  <table style="background:#eff6ff;border-radius:12px;padding:12px 16px;margin:12px 0">{lignes_html}</table>
  {bouton}
</div>"""
        destinataires = [x for x in settings.demandes_email_alerte.split(",") if x.strip()]
        try:
            envoyer_email(destinataires, sujet, texte, contenu_html)
            d.email_alerte_at = datetime.now(timezone.utc)
            db.commit()
        except ErreurEmail as err:
            log.warning("Alerte e-mail de la demande %s non envoyée : %s", d.id, err)
    finally:
        db.close()


# ── App chauffeur ──────────────────────────────────────────────────────────

@router.post("", response_model=DemandeOut, status_code=201)
def creer_demande(
    data: DemandeIn,
    taches: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_chauffeur),
):
    nature = data.nature.strip().upper()
    if nature not in NATURES_DEMANDE:
        raise HTTPException(400, f"Nature invalide (valeurs : {', '.join(NATURES_DEMANDE)})")
    d = DemandeVehicule(
        user_id=user.id, nature=nature,
        immatriculation=data.immatriculation.strip().upper(),
        kilometrage=data.kilometrage, position=data.position.strip(), technicien=data.technicien.strip(),
        description=(data.description or "").strip() or None,
        nom_chauffeur=user.full_name or user.username, telephone=user.telephone, statut="NOUVELLE",
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    taches.add_task(_alerter_par_email, d.id)
    return d


@router.get("/mes", response_model=DemandePage)
def mes_demandes(
    q: str | None = Query(None, description="Recherche : type, nature, immatriculation, position, technicien"),
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_chauffeur),
):
    req = db.query(DemandeVehicule).filter(DemandeVehicule.user_id == user.id)
    if q and q.strip():
        motif = f"%{q.strip()}%"
        texte = q.strip().lower()
        # « panne », « vidange », « remontee » / « remontée » : recherche aussi par type
        natures = [code for code, libelle in NATURES_DEMANDE.items()
                   if texte in libelle.lower() or texte in code.lower()]
        conditions = [DemandeVehicule.immatriculation.ilike(motif), DemandeVehicule.description.ilike(motif),
                      DemandeVehicule.position.ilike(motif), DemandeVehicule.technicien.ilike(motif)]
        if natures:
            conditions.append(DemandeVehicule.nature.in_(natures))
        req = req.filter(or_(*conditions))
    total = req.count()
    items = req.order_by(DemandeVehicule.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return DemandePage(items=items, total=total)


# ── Plateforme de gestion ──────────────────────────────────────────────────

@router.get("", response_model=DemandePage)
def lister(
    nature: str | None = None,
    statut: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    req = db.query(DemandeVehicule)
    if nature:
        req = req.filter(DemandeVehicule.nature == nature.upper())
    if statut:
        req = req.filter(DemandeVehicule.statut == statut.upper())
    if q and q.strip():
        motif = f"%{q.strip()}%"
        req = req.filter(or_(DemandeVehicule.immatriculation.ilike(motif), DemandeVehicule.nom_chauffeur.ilike(motif),
                             DemandeVehicule.technicien.ilike(motif), DemandeVehicule.position.ilike(motif),
                             DemandeVehicule.description.ilike(motif)))
    total = req.count()
    items = req.order_by(DemandeVehicule.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return DemandePage(items=items, total=total)


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Compteurs pour la page et la cloche de notification (demandes « nouvelles »)."""
    lignes = db.query(DemandeVehicule.nature, DemandeVehicule.statut, func.count()).group_by(
        DemandeVehicule.nature, DemandeVehicule.statut).all()
    par_nature = {n: {s: 0 for s in STATUTS_DEMANDE} for n in NATURES_DEMANDE}
    for n, s, c in lignes:
        par_nature.setdefault(n, {s2: 0 for s2 in STATUTS_DEMANDE})[s] = c
    nouvelles = sum(v.get("NOUVELLE", 0) for v in par_nature.values())
    derniere = db.query(func.max(DemandeVehicule.created_at)).filter(DemandeVehicule.statut == "NOUVELLE").scalar()
    return {"nouvelles": nouvelles, "par_nature": par_nature, "derniere_nouvelle": derniere,
            "total": sum(sum(v.values()) for v in par_nature.values())}


@router.patch("/{demande_id}", response_model=DemandeOut)
def mettre_a_jour(
    demande_id: int,
    data: DemandeMaj,
    taches: BackgroundTasks,
    db: Session = Depends(get_db),
    auteur: User = Depends(require_editor),
):
    d = db.get(DemandeVehicule, demande_id)
    if not d:
        raise HTTPException(404, "Demande introuvable")
    statut = data.statut.strip().upper()
    if statut not in STATUTS_DEMANDE:
        raise HTTPException(400, f"Statut invalide (valeurs : {', '.join(STATUTS_DEMANDE)})")
    change = statut != d.statut
    d.statut = statut
    if data.commentaire is not None:
        d.commentaire = data.commentaire.strip()[:1000] or None
    d.traitee_par = auteur.full_name or auteur.username
    if change and d.user_id:
        # Le chauffeur est prévenu dans son app (et sur son téléphone)
        nature = NATURES_DEMANDE.get(d.nature, d.nature)
        titre = f"Demande {nature.lower()} {STATUTS_DEMANDE[statut].lower()}"
        message = f"{d.immatriculation}" + (f" — {d.commentaire}" if d.commentaire else "")
        notifier(db, d.user_id, "DEMANDE", titre, message, {"demande_id": d.id})
        taches.add_task(envoyer_push, [d.user_id], titre, message, {"demande_id": d.id})
    db.commit()
    db.refresh(d)
    return d
