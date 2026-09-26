from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..database import get_db
from ..models.user import User
from ..services.auth_service import (
    verify_password, hash_password, create_access_token,
    get_authenticated_user, get_current_user, require_admin,
)

router = APIRouter(prefix="/api/auth", tags=["Authentification"])

VALID_ROLES = {"ADMIN", "EDITOR", "HSE", "VIEWER", "CHAUFFEUR"}


# ── Schémas ────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    username:     str
    full_name:    str | None
    role:         str = "EDITOR"


class UserOut(BaseModel):
    id:        int
    username:  str
    full_name: str | None
    email:     str | None
    is_active: bool
    role:      str = "EDITOR"
    vehicule_plaque: str | None = None
    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username:  str
    password:  str
    full_name: str | None = None
    email:     str | None = None
    role:      str = "EDITOR"
    vehicule_plaque: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    email:     str | None = None
    role:      str | None = None
    is_active: bool | None = None
    password:  str | None = None
    vehicule_plaque: str | None = None


def _vide_en_none(val: str | None) -> str | None:
    """Le formulaire envoie "" pour un champ laissé vide : sans ça, deux comptes sans
    email entrent en conflit sur la contrainte d'unicité."""
    val = (val or "").strip()
    return val or None


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")

    token = create_access_token({"sub": user.username})
    return TokenResponse(access_token=token, username=user.username, full_name=user.full_name, role=user.role)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_authenticated_user)):
    return current_user


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Nom d'utilisateur déjà utilisé")
    if data.role not in VALID_ROLES:
        raise HTTPException(400, f"Rôle invalide. Valeurs possibles : {', '.join(sorted(VALID_ROLES))}")
    email = _vide_en_none(data.email)
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email déjà utilisé par un autre compte")
    user = User(
        username=data.username,
        full_name=_vide_en_none(data.full_name),
        email=email,
        hashed_password=hash_password(data.password),
        role=data.role,
        vehicule_plaque=_vide_en_none(data.vehicule_plaque),
    )
    db.add(user); db.commit(); db.refresh(user)
    return user


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
        user.vehicule_plaque = _vide_en_none(data.vehicule_plaque)
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
