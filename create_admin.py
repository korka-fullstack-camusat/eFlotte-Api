"""
Crée (ou met à jour) un compte administrateur en posant les questions dans le terminal.

    docker exec -it eflotte-api python create_admin.py

Si le nom d'utilisateur existe déjà, le compte passe ADMIN, est réactivé et
prend le nouveau mot de passe (après confirmation).
"""
import getpass
import sys

from app.database import SessionLocal
from app.models import User
from app.services.auth_service import hash_password

MIN_PASSWORD_LENGTH = 8


def ask(label: str, required: bool = False) -> str | None:
    while True:
        value = input(f"{label}{' *' if required else ''} : ").strip()
        if value or not required:
            return value or None
        print("  → Champ obligatoire.")


def ask_password() -> str:
    while True:
        password = getpass.getpass(f"Mot de passe * (min. {MIN_PASSWORD_LENGTH} caractères) : ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"  → Au moins {MIN_PASSWORD_LENGTH} caractères.")
            continue
        if getpass.getpass("Confirmer le mot de passe * : ") != password:
            print("  → Les mots de passe ne correspondent pas.")
            continue
        return password


def main() -> None:
    print("=== Création d'un compte administrateur eFlotte ===\n")
    db = SessionLocal()
    try:
        username = ask("Nom d'utilisateur", required=True)
        user = db.query(User).filter(User.username == username).first()
        if user:
            answer = input(f"Le compte « {username} » existe déjà. Le passer ADMIN et changer son mot de passe ? [o/N] : ")
            if answer.strip().lower() not in ("o", "oui", "y", "yes"):
                print("Annulé, rien n'a été modifié.")
                return
        else:
            user = User(username=username)

        full_name = ask("Nom complet")
        email = ask("Email")
        if email and db.query(User).filter(User.email == email, User.username != username).first():
            print(f"✗ L'email « {email} » est déjà utilisé par un autre compte.")
            sys.exit(1)
        password = ask_password()

        if full_name:
            user.full_name = full_name
        if email:
            user.email = email
        user.hashed_password = hash_password(password)
        user.role = "ADMIN"
        user.is_active = True
        db.add(user)
        db.commit()
        print(f"\n✓ Compte administrateur « {username} » prêt. Connexion sur le front avec ces identifiants.")
    except (KeyboardInterrupt, EOFError):
        print("\nAnnulé, rien n'a été modifié.")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
