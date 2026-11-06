"""Un véhicule n'est attribué qu'à un seul compte à la fois."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.user import User


def cle_plaque(plaque: str | None) -> str:
    """« aa-512-ys » et « AA 512 YS » désignent le même véhicule."""
    return "".join(c for c in (plaque or "").upper() if c.isalnum())


def titulaire_plaque(db: Session, plaque: str | None, sauf_user_id: int | None = None) -> User | None:
    """Compte qui a déjà ce véhicule attribué (autre que sauf_user_id), sinon None."""
    cle = cle_plaque(plaque)
    if not cle:
        return None
    q = db.query(User).filter(
        func.upper(func.replace(func.replace(User.vehicule_plaque, " ", ""), "-", "")) == cle)
    if sauf_user_id is not None:
        q = q.filter(User.id != sauf_user_id)
    return q.first()


def message_deja_attribue(plaque: str, titulaire: User) -> str:
    return f"Le véhicule {plaque} est déjà attribué à {titulaire.full_name or titulaire.username}."
