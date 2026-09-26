"""
Checklists inspection / restitution envoyées depuis l'app mobile chauffeur,
et leur suivi côté plateforme (liste, détail, relances).
"""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.inspection import PhotoInspection, RapportInspection, RelanceChecklist
from ..models.user import User
from ..models.vehicule import Vehicule
from ..services.auth_service import (
    get_authenticated_user, get_current_user, require_chauffeur, require_editor,
)
from ..services.checklist_modele import PHOTOS, modele_public, valider_reponses

router = APIRouter(prefix="/api/inspections", tags=["Checklists mobiles"])

POSITIONS_PHOTOS = [p for p, _ in PHOTOS]
TYPES_RAPPORT = {"INSPECTION", "RESTITUTION"}
PHOTO_MAX_OCTETS = 5 * 1024 * 1024
SIGNATURE_MAX_CARACTERES = 500_000
SIGNATURE_PREFIXE = "data:image/png;base64,"


# ── Schémas ────────────────────────────────────────────────────────────────

class RapportResume(BaseModel):
    id: int
    user_id: int | None
    type_rapport: str
    date_rapport: date
    immatriculation: str
    marque: str | None
    modele: str | None
    nom_chauffeur: str
    kilometrage: int
    nb_non_conformes: int
    nb_critiques: int
    created_at: datetime
    model_config = {"from_attributes": True}


class RapportDetail(RapportResume):
    filiale: str | None
    visite_technique: date | None
    reponses: dict
    commentaires: str | None
    nom_instructeur: str | None
    signature: str | None
    photos: list[str] = []


class RapportPage(BaseModel):
    items: list[RapportResume]
    total: int


class RelanceOut(BaseModel):
    id: int
    envoye_par: str | None
    message: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class VehiculeMini(BaseModel):
    plaque_immatriculation: str
    marque: str | None
    modele: str | None
    kilometrage: int | None = None
    # Dernière date de visite technique connue (relevée dans un rapport précédent)
    visite_technique: date | None = None
    model_config = {"from_attributes": True}


class MonEspace(BaseModel):
    username: str
    full_name: str | None
    email: str | None
    nb_rapports: int
    vehicule: VehiculeMini | None
    vehicule_plaque: str | None
    filiale: str | None
    envoye_cette_semaine: bool
    dernier_rapport: RapportResume | None
    derniers_rapports: list[RapportResume]
    relances: list[RelanceOut]
    filiale_precedente: str | None


class SuiviChauffeur(BaseModel):
    user_id: int
    username: str
    full_name: str | None
    vehicule_plaque: str | None
    envoye_cette_semaine: bool
    dernier_rapport_id: int | None
    dernier_rapport_date: date | None
    dernier_rapport_critiques: int | None
    nb_rapports: int
    relances_en_attente: int
    derniere_relance: datetime | None


class StatsInspections(BaseModel):
    semaine_debut: date
    nb_chauffeurs: int
    chauffeurs_a_jour: int
    chauffeurs_en_retard: int
    rapports_semaine: int
    rapports_critiques_semaine: int


class RelanceIn(BaseModel):
    user_id: int
    message: str | None = None


class RelanceGroupeeIn(BaseModel):
    message: str | None = None


# ── Utilitaires ────────────────────────────────────────────────────────────

def _debut_semaine(jour: date | None = None) -> date:
    """Lundi de la semaine en cours (les points sont à vérifier chaque semaine)."""
    jour = jour or date.today()
    return jour - timedelta(days=jour.weekday())


def _chauffeurs_actifs(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.role == "CHAUFFEUR", User.is_active.is_(True))
        .order_by(User.full_name, User.username)
        .all()
    )


def _ids_a_jour(db: Session, debut: date) -> set[int]:
    rows = (
        db.query(RapportInspection.user_id)
        .filter(RapportInspection.date_rapport >= debut, RapportInspection.user_id.isnot(None))
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


def _vehicule_mini(db: Session, plaque: str | None) -> Vehicule | None:
    if not plaque:
        return None
    return db.query(Vehicule).filter(Vehicule.plaque_immatriculation == plaque).first()


def _visites_techniques(db: Session, plaques: list[str] | None = None) -> dict[str, date]:
    """Dernière date de visite technique relevée par plaque."""
    q = (
        db.query(RapportInspection.immatriculation, func.max(RapportInspection.visite_technique))
        .filter(RapportInspection.visite_technique.isnot(None))
    )
    if plaques is not None:
        q = q.filter(RapportInspection.immatriculation.in_(plaques))
    return dict(q.group_by(RapportInspection.immatriculation).all())


def _avec_visite(v: Vehicule, visites: dict[str, date]) -> VehiculeMini:
    mini = VehiculeMini.model_validate(v, from_attributes=True)
    mini.visite_technique = visites.get(v.plaque_immatriculation)
    return mini


def _detail(db: Session, rapport: RapportInspection) -> RapportDetail:
    positions = [
        p for (p,) in db.query(PhotoInspection.position).filter(PhotoInspection.rapport_id == rapport.id).all()
    ]
    detail = RapportDetail.model_validate(rapport, from_attributes=True)
    detail.photos = [p for p in POSITIONS_PHOTOS if p in positions]
    return detail


def _peut_voir(user: User, rapport: RapportInspection) -> bool:
    return user.role != "CHAUFFEUR" or rapport.user_id == user.id


def _rapport_ou_404(db: Session, rapport_id: int, user: User) -> RapportInspection:
    rapport = db.query(RapportInspection).filter(RapportInspection.id == rapport_id).first()
    # 404 aussi quand ce n'est pas le sien : ne pas révéler l'existence des rapports des autres
    if not rapport or not _peut_voir(user, rapport):
        raise HTTPException(404, "Rapport introuvable")
    return rapport


# ── Commun ─────────────────────────────────────────────────────────────────

@router.get("/modele")
def get_modele(_: User = Depends(get_authenticated_user)):
    """Sections, points de contrôle et photos du formulaire."""
    return modele_public()


@router.get("/rapports/{rapport_id}", response_model=RapportDetail)
def get_rapport(
    rapport_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
):
    return _detail(db, _rapport_ou_404(db, rapport_id, user))


@router.get("/rapports/{rapport_id}/photos/{position}")
def get_photo(
    rapport_id: int,
    position: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
):
    _rapport_ou_404(db, rapport_id, user)
    photo = (
        db.query(PhotoInspection)
        .filter(PhotoInspection.rapport_id == rapport_id, PhotoInspection.position == position)
        .first()
    )
    if not photo:
        raise HTTPException(404, "Photo introuvable")
    return Response(
        content=photo.data,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ── App chauffeur ──────────────────────────────────────────────────────────

@router.get("/moi", response_model=MonEspace)
def mon_espace(db: Session = Depends(get_db), user: User = Depends(require_chauffeur)):
    mes = db.query(RapportInspection).filter(RapportInspection.user_id == user.id)
    derniers = mes.order_by(RapportInspection.created_at.desc()).limit(3).all()
    relances = (
        db.query(RelanceChecklist)
        .filter(RelanceChecklist.user_id == user.id, RelanceChecklist.resolue_at.is_(None))
        .order_by(RelanceChecklist.created_at.desc())
        .all()
    )
    vehicule = _vehicule_mini(db, user.vehicule_plaque)
    return MonEspace(
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        nb_rapports=mes.count(),
        vehicule=_avec_visite(vehicule, _visites_techniques(db, [vehicule.plaque_immatriculation])) if vehicule else None,
        vehicule_plaque=user.vehicule_plaque,
        # Anciens comptes : reprendre la filiale saisie dans leurs rapports précédents
        filiale=user.filiale or (derniers[0].filiale if derniers else None),
        envoye_cette_semaine=mes.filter(RapportInspection.date_rapport >= _debut_semaine()).count() > 0,
        dernier_rapport=derniers[0] if derniers else None,
        derniers_rapports=derniers,
        relances=relances,
        filiale_precedente=derniers[0].filiale if derniers else None,
    )


@router.get("/vehicules", response_model=list[VehiculeMini])
def vehicules_disponibles(db: Session = Depends(get_db), _: User = Depends(require_chauffeur)):
    """Liste réduite de la flotte pour choisir un autre véhicule que celui attribué."""
    visites = _visites_techniques(db)
    return [_avec_visite(v, visites) for v in db.query(Vehicule).order_by(Vehicule.plaque_immatriculation).all()]


@router.get("/mes-rapports", response_model=RapportPage)
def mes_rapports(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_chauffeur),
):
    q = db.query(RapportInspection).filter(RapportInspection.user_id == user.id)
    total = q.count()
    items = (
        q.order_by(RapportInspection.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return RapportPage(items=items, total=total)


@router.post("/rapports", response_model=RapportDetail, status_code=201)
async def envoyer_rapport(
    data: str = Form(..., description="Rapport au format JSON"),
    photo_DEVANT: UploadFile = File(...),
    photo_ARRIERE: UploadFile = File(...),
    photo_GAUCHE: UploadFile = File(...),
    photo_DROITE: UploadFile = File(...),
    photo_INTERIEUR_AVANT: UploadFile = File(...),
    photo_INTERIEUR_ARRIERE: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_chauffeur),
):
    try:
        payload = json.loads(data)
        assert isinstance(payload, dict)
    except (ValueError, AssertionError):
        raise HTTPException(400, "Données du rapport illisibles")

    type_rapport = payload.get("type_rapport") or "INSPECTION"
    if type_rapport not in TYPES_RAPPORT:
        raise HTTPException(400, "Type de rapport invalide")

    # Le véhicule est celui du compte. S'il n'y en a pas encore, celui choisi
    # dans ce premier rapport est enregistré sur le compte pour les suivants.
    plaque = user.vehicule_plaque or str(payload.get("immatriculation") or "").strip()
    vehicule = _vehicule_mini(db, plaque)
    if not vehicule:
        raise HTTPException(400, "Véhicule introuvable dans la flotte")

    try:
        kilometrage = int(payload.get("kilometrage"))
        assert 0 <= kilometrage <= 5_000_000
    except (TypeError, ValueError, AssertionError):
        raise HTTPException(400, "Kilométrage invalide")

    visite_technique = None
    if payload.get("visite_technique"):
        try:
            visite_technique = date.fromisoformat(payload["visite_technique"])
        except ValueError:
            raise HTTPException(400, "Date de visite technique invalide")
    else:
        # Déjà connue : le formulaire ne la redemande pas, on reprend la dernière relevée
        visite_technique = _visites_techniques(db, [vehicule.plaque_immatriculation]).get(vehicule.plaque_immatriculation)

    try:
        reponses, nb_nc, nb_crit = valider_reponses(payload.get("reponses") or {})
    except ValueError as e:
        raise HTTPException(400, str(e))

    signature = payload.get("signature") or ""
    if not signature.startswith(SIGNATURE_PREFIXE) or len(signature) > SIGNATURE_MAX_CARACTERES:
        raise HTTPException(400, "Signature du conducteur manquante")

    nom_instructeur = (payload.get("nom_instructeur") or "").strip()[:150] or None

    photos = {
        "DEVANT": photo_DEVANT, "ARRIERE": photo_ARRIERE, "GAUCHE": photo_GAUCHE,
        "DROITE": photo_DROITE, "INTERIEUR_AVANT": photo_INTERIEUR_AVANT,
        "INTERIEUR_ARRIERE": photo_INTERIEUR_ARRIERE,
    }
    contenus: dict[str, tuple[str, bytes]] = {}
    for position, fichier in photos.items():
        if not (fichier.content_type or "").startswith("image/"):
            raise HTTPException(400, f"La photo « {position} » n'est pas une image")
        contenu = await fichier.read()
        if not contenu:
            raise HTTPException(400, f"La photo « {position} » est vide")
        if len(contenu) > PHOTO_MAX_OCTETS:
            raise HTTPException(400, f"La photo « {position} » dépasse 5 Mo")
        contenus[position] = (fichier.content_type, contenu)

    # Filiale : celle du compte ; sinon saisie une fois ici et enregistrée sur le compte
    precedent = (
        db.query(RapportInspection.filiale)
        .filter(RapportInspection.user_id == user.id, RapportInspection.filiale.isnot(None))
        .order_by(RapportInspection.created_at.desc()).first()
    )
    filiale = (
        user.filiale or (payload.get("filiale") or "").strip()[:150]
        or (precedent[0] if precedent else None) or None
    )
    if not user.filiale and filiale:
        user.filiale = filiale
    if not user.vehicule_plaque:
        user.vehicule_plaque = vehicule.plaque_immatriculation

    rapport = RapportInspection(
        user_id=user.id,
        type_rapport=type_rapport,
        date_rapport=date.today(),
        immatriculation=vehicule.plaque_immatriculation,
        marque=vehicule.marque,
        modele=vehicule.modele,
        filiale=filiale,
        nom_chauffeur=user.full_name or user.username,
        kilometrage=kilometrage,
        visite_technique=visite_technique,
        reponses=reponses,
        commentaires=(payload.get("commentaires") or "").strip()[:2000] or None,
        nom_instructeur=nom_instructeur,
        signature=signature,
        nb_non_conformes=nb_nc,
        nb_critiques=nb_crit,
    )
    db.add(rapport)
    db.flush()
    for position, (content_type, contenu) in contenus.items():
        db.add(PhotoInspection(rapport_id=rapport.id, position=position, content_type=content_type, data=contenu))

    # Le kilométrage relevé met à jour la fiche du véhicule s'il est plus récent
    if vehicule.kilometrage is None or kilometrage > vehicule.kilometrage:
        vehicule.kilometrage = kilometrage

    # Un envoi clôt les relances en attente
    db.query(RelanceChecklist).filter(
        RelanceChecklist.user_id == user.id, RelanceChecklist.resolue_at.is_(None)
    ).update({RelanceChecklist.resolue_at: datetime.now(timezone.utc)}, synchronize_session=False)

    db.commit()
    db.refresh(rapport)
    return _detail(db, rapport)


# ── Plateforme de gestion ──────────────────────────────────────────────────

@router.get("/stats", response_model=StatsInspections)
def stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    debut = _debut_semaine()
    chauffeurs = _chauffeurs_actifs(db)
    a_jour = _ids_a_jour(db, debut)
    nb_a_jour = sum(1 for c in chauffeurs if c.id in a_jour)
    semaine = db.query(RapportInspection).filter(RapportInspection.date_rapport >= debut)
    return StatsInspections(
        semaine_debut=debut,
        nb_chauffeurs=len(chauffeurs),
        chauffeurs_a_jour=nb_a_jour,
        chauffeurs_en_retard=len(chauffeurs) - nb_a_jour,
        rapports_semaine=semaine.count(),
        rapports_critiques_semaine=semaine.filter(RapportInspection.nb_critiques > 0).count(),
    )


@router.get("/suivi", response_model=list[SuiviChauffeur])
def suivi_chauffeurs(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Un chauffeur par ligne : a-t-il envoyé sa checklist cette semaine, relances en attente."""
    debut = _debut_semaine()
    chauffeurs = _chauffeurs_actifs(db)
    a_jour = _ids_a_jour(db, debut)

    nb_par_user = dict(
        db.query(RapportInspection.user_id, func.count(RapportInspection.id))
        .group_by(RapportInspection.user_id).all()
    )
    dernier_id_par_user = dict(
        db.query(RapportInspection.user_id, func.max(RapportInspection.id))
        .group_by(RapportInspection.user_id).all()
    )
    derniers = {
        r.id: r for r in db.query(RapportInspection)
        .filter(RapportInspection.id.in_([i for i in dernier_id_par_user.values() if i]))
        .all()
    }
    relances = (
        db.query(
            RelanceChecklist.user_id,
            func.count(RelanceChecklist.id),
            func.max(RelanceChecklist.created_at),
        )
        .filter(RelanceChecklist.resolue_at.is_(None))
        .group_by(RelanceChecklist.user_id)
        .all()
    )
    relances_par_user = {uid: (nb, der) for uid, nb, der in relances}

    lignes = []
    for c in chauffeurs:
        dernier = derniers.get(dernier_id_par_user.get(c.id))
        nb_rel, der_rel = relances_par_user.get(c.id, (0, None))
        lignes.append(SuiviChauffeur(
            user_id=c.id,
            username=c.username,
            full_name=c.full_name,
            vehicule_plaque=c.vehicule_plaque,
            envoye_cette_semaine=c.id in a_jour,
            dernier_rapport_id=dernier.id if dernier else None,
            dernier_rapport_date=dernier.date_rapport if dernier else None,
            dernier_rapport_critiques=dernier.nb_critiques if dernier else None,
            nb_rapports=nb_par_user.get(c.id, 0),
            relances_en_attente=nb_rel,
            derniere_relance=der_rel,
        ))
    # En retard d'abord
    lignes.sort(key=lambda l: (l.envoye_cette_semaine, (l.full_name or l.username).lower()))
    return lignes


@router.get("/rapports", response_model=RapportPage)
def list_rapports(
    q: str | None = Query(None, description="Chauffeur ou immatriculation"),
    statut: str | None = Query(None, pattern="^(conforme|anomalies|critique)$"),
    type_rapport: str | None = Query(None),
    user_id: int | None = Query(None),
    date_debut: date | None = Query(None),
    date_fin: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(RapportInspection)
    if q:
        motif = f"%{q.strip()}%"
        query = query.filter(or_(
            RapportInspection.nom_chauffeur.ilike(motif),
            RapportInspection.immatriculation.ilike(motif),
        ))
    if statut == "conforme":
        query = query.filter(RapportInspection.nb_non_conformes == 0)
    elif statut == "anomalies":
        query = query.filter(RapportInspection.nb_non_conformes > 0)
    elif statut == "critique":
        query = query.filter(RapportInspection.nb_critiques > 0)
    if type_rapport in TYPES_RAPPORT:
        query = query.filter(RapportInspection.type_rapport == type_rapport)
    if user_id:
        query = query.filter(RapportInspection.user_id == user_id)
    if date_debut:
        query = query.filter(RapportInspection.date_rapport >= date_debut)
    if date_fin:
        query = query.filter(RapportInspection.date_rapport <= date_fin)
    total = query.count()
    items = (
        query.order_by(RapportInspection.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return RapportPage(items=items, total=total)


def _creer_relance(db: Session, chauffeur: User, auteur: User, message: str | None) -> RelanceChecklist:
    relance = RelanceChecklist(
        user_id=chauffeur.id,
        envoye_par=auteur.full_name or auteur.username,
        message=(message or "").strip()[:500] or None,
    )
    db.add(relance)
    return relance


@router.post("/relances", response_model=RelanceOut, status_code=201)
def relancer(data: RelanceIn, db: Session = Depends(get_db), auteur: User = Depends(require_editor)):
    chauffeur = db.query(User).filter(User.id == data.user_id, User.role == "CHAUFFEUR").first()
    if not chauffeur:
        raise HTTPException(404, "Chauffeur introuvable")
    if not chauffeur.is_active:
        raise HTTPException(400, "Ce compte est désactivé")
    relance = _creer_relance(db, chauffeur, auteur, data.message)
    db.commit()
    db.refresh(relance)
    return relance


@router.post("/relances/en-retard")
def relancer_en_retard(
    data: RelanceGroupeeIn,
    db: Session = Depends(get_db),
    auteur: User = Depends(require_editor),
):
    """Relance d'un coup tous les chauffeurs qui n'ont pas envoyé leur checklist cette semaine."""
    a_jour = _ids_a_jour(db, _debut_semaine())
    en_retard = [c for c in _chauffeurs_actifs(db) if c.id not in a_jour]
    for c in en_retard:
        _creer_relance(db, c, auteur, data.message)
    db.commit()
    return {"relances": len(en_retard)}
