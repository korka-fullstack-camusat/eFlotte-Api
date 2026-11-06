from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy import func
from ..config import settings
from ..database import get_db
from ..models.user import User
from ..services.attribution import cle_plaque, message_deja_attribue, titulaire_plaque
from ..services.auth_service import (
    verify_password, hash_password, create_access_token,
    get_authenticated_user, get_current_user, require_admin,
)
from ..services.sms import client_sms, normaliser_telephone

router = APIRouter(prefix="/api/auth", tags=["Authentification"])

VALID_ROLES = {"ADMIN", "EDITOR", "HSE", "VIEWER", "CHAUFFEUR"}


# ── Schémas ────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    username:     str
    full_name:    str | None
    role:         str = "EDITOR"
    doit_changer_mdp: bool = False


class UserOut(BaseModel):
    id:        int
    username:  str
    full_name: str | None
    email:     str | None
    is_active: bool
    role:      str = "EDITOR"
    vehicule_plaque: str | None = None
    filiale:   str | None = None
    telephone: str | None = None
    doit_changer_mdp: bool = False
    identifiants_envoyes_at: datetime | None = None
    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username:  str
    # Chauffeur : facultatif, le mot de passe initial commun (Camusat@2026) est utilisé
    password:  str | None = None
    full_name: str | None = None
    email:     str | None = None
    role:      str = "EDITOR"
    vehicule_plaque: str | None = None
    filiale:   str | None = None
    telephone: str | None = None
    # Compte chauffeur : identifiants envoyés par SMS au numéro saisi
    envoyer_sms: bool = True


class UserCreeOut(UserOut):
    """Compte créé + résultat de l'envoi des identifiants par SMS (chauffeurs)."""
    sms: str | None = None            # ENVOYE | ECHEC | NON_CONFIGURE | SANS_NUMERO | None (non demandé)
    sms_message: str | None = None
    mot_de_passe_initial: str | None = None   # chauffeur : mot de passe envoyé (à transmettre si le SMS échoue)


class UserUpdate(BaseModel):
    full_name: str | None = None
    email:     str | None = None
    role:      str | None = None
    is_active: bool | None = None
    password:  str | None = None
    vehicule_plaque: str | None = None
    filiale:   str | None = None
    telephone: str | None = None


class ChangementMotDePasse(BaseModel):
    ancien: str
    nouveau: str


def _vide_en_none(val: str | None) -> str | None:
    """Le formulaire envoie "" pour un champ laissé vide : sans ça, deux comptes sans
    email entrent en conflit sur la contrainte d'unicité."""
    val = (val or "").strip()
    return val or None


def _telephone(val: str | None) -> str | None:
    if not _vide_en_none(val):
        return None
    tel = normaliser_telephone(val)
    if not tel:
        raise HTTPException(400, "Numéro de téléphone invalide (ex : 77 123 45 67 ou +221771234567)")
    return tel


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Sur téléphone, le clavier ajoute souvent une majuscule ou un espace final :
    # correspondance exacte d'abord, sinon sans tenir compte de la casse (si un seul compte correspond).
    username = form.username.strip()
    user = db.query(User).filter(User.username == username).first()
    if not user:
        candidats = db.query(User).filter(func.lower(User.username) == username.lower()).limit(2).all()
        user = candidats[0] if len(candidats) == 1 else None
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")

    token = create_access_token({"sub": user.username})
    return TokenResponse(access_token=token, username=user.username, full_name=user.full_name, role=user.role,
                         doit_changer_mdp=bool(user.doit_changer_mdp))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_authenticated_user)):
    return current_user


@router.post("/me/mot-de-passe", status_code=204)
def changer_mot_de_passe(
    data: ChangementMotDePasse,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """Chaque utilisateur (chauffeur compris) change son propre mot de passe."""
    if not verify_password(data.ancien, current_user.hashed_password):
        raise HTTPException(400, "Mot de passe actuel incorrect")
    if len(data.nouveau) < 6:
        raise HTTPException(400, "Le nouveau mot de passe doit contenir au moins 6 caractères")
    if data.nouveau == data.ancien:
        raise HTTPException(400, "Le nouveau mot de passe doit être différent de l'actuel")
    current_user.hashed_password = hash_password(data.nouveau)
    current_user.doit_changer_mdp = False
    db.commit()


@router.post("/users", response_model=UserCreeOut, status_code=201)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    data.username = data.username.strip()
    if not data.username:
        raise HTTPException(400, "Nom d'utilisateur obligatoire")
    if db.query(User).filter(func.lower(User.username) == data.username.lower()).first():
        raise HTTPException(400, "Nom d'utilisateur déjà utilisé")
    if data.role not in VALID_ROLES:
        raise HTTPException(400, f"Rôle invalide. Valeurs possibles : {', '.join(sorted(VALID_ROLES))}")
    chauffeur = data.role == "CHAUFFEUR"
    telephone = _telephone(data.telephone)
    if chauffeur:
        # Chauffeur : identifiant, téléphone, véhicule. Mot de passe initial commun envoyé par SMS.
        if not telephone:
            raise HTTPException(400, "Le téléphone est obligatoire pour un compte chauffeur (il reçoit ses identifiants par SMS)")
        if db.query(User).filter(User.telephone == telephone).first():
            raise HTTPException(400, "Ce numéro de téléphone est déjà associé à un compte")
        mot_de_passe = _vide_en_none(data.password) or settings.chauffeur_mot_de_passe_initial
    else:
        mot_de_passe = data.password or ""
        if len(mot_de_passe) < 6:
            raise HTTPException(400, "Mot de passe obligatoire (au moins 6 caractères)")
    email = _vide_en_none(data.email)
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email déjà utilisé par un autre compte")
    plaque = _vide_en_none(data.vehicule_plaque)
    if plaque and (titulaire := titulaire_plaque(db, plaque)):
        raise HTTPException(400, message_deja_attribue(plaque, titulaire))
    user = User(
        username=data.username,
        full_name=_vide_en_none(data.full_name),
        email=email,
        hashed_password=hash_password(mot_de_passe),
        role=data.role,
        vehicule_plaque=_vide_en_none(data.vehicule_plaque),
        filiale=_vide_en_none(data.filiale),
        telephone=telephone,
        # Chauffeur : le mot de passe reçu par SMS est à remplacer à la 1re connexion
        doit_changer_mdp=chauffeur,
    )
    db.add(user); db.commit(); db.refresh(user)
    out = UserCreeOut.model_validate(user)
    if chauffeur:
        out.mot_de_passe_initial = mot_de_passe
    if chauffeur and data.envoyer_sms:
        from .comptes_chauffeurs import envoyer_identifiants_sms
        with client_sms() as client:
            out.sms, out.sms_message = envoyer_identifiants_sms(user, client, mot_de_passe)
        db.commit()
        out.identifiants_envoyes_at = user.identifiants_envoyes_at
    return out


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(User).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")

    if data.role is not None:
        if data.role not in VALID_ROLES:
            raise HTTPException(400, f"Rôle invalide. Valeurs possibles : {', '.join(sorted(VALID_ROLES))}")
        user.role = data.role
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.email is not None:
        email = _vide_en_none(data.email)
        if email and db.query(User).filter(User.email == email, User.id != user.id).first():
            raise HTTPException(400, "Email déjà utilisé par un autre compte")
        user.email = email
    if data.vehicule_plaque is not None:
        plaque = _vide_en_none(data.vehicule_plaque)
        change = cle_plaque(plaque) != cle_plaque(user.vehicule_plaque)
        if plaque and change and (titulaire := titulaire_plaque(db, plaque, sauf_user_id=user.id)):
            raise HTTPException(400, message_deja_attribue(plaque, titulaire))
        user.vehicule_plaque = plaque
    if data.filiale is not None:
        user.filiale = _vide_en_none(data.filiale)
    if data.telephone is not None:
        user.telephone = _telephone(data.telephone)
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        if len(data.password) < 6:
            raise HTTPException(400, "Le mot de passe doit contenir au moins 6 caractères")
        user.hashed_password = hash_password(data.password)

    db.commit(); db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    db.delete(user); db.commit()
