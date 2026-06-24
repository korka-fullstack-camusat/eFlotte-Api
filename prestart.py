"""
Script d'initialisation exécuté UNE FOIS avant le démarrage de gunicorn.
Crée les tables et l'utilisateur admin par défaut.
"""
import time
import sqlalchemy
from app.database import Base, engine, SessionLocal
from app.models import (  # noqa: F401 — tous importés pour Base.metadata.create_all()
    User, Vehicule, CoutFlotte, EntretienVehicule, EntretienBis,
    MissionChauffeur, SuiviDevis, CheckListVL, SuiviPanne,
    Pneumatique, SuiviSinistre, ImportGlobalLog,
)
from app.services.auth_service import hash_password

print("→ Attente de la base de données...")
for attempt in range(30):
    try:
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        print("✓ Base de données disponible.")
        break
    except Exception:
        print(f"  Base non prête, nouvelle tentative ({attempt + 1}/30)...")
        time.sleep(2)
else:
    print("✗ Impossible de se connecter à la base de données après 30 tentatives.")
    raise SystemExit(1)

print("→ Création des tables...")
Base.metadata.create_all(bind=engine)
print("✓ Tables prêtes.")

print("→ Vérification des colonnes additionnelles...")
with engine.begin() as conn:
    conn.execute(sqlalchemy.text("""
        ALTER TABLE vehicules
            ADD COLUMN IF NOT EXISTS marque VARCHAR(100),
            ADD COLUMN IF NOT EXISTS annee INTEGER,
            ADD COLUMN IF NOT EXISTS statut VARCHAR(30),
            ADD COLUMN IF NOT EXISTS chauffeur VARCHAR(150),
            ADD COLUMN IF NOT EXISTS kilometrage INTEGER,
            ADD COLUMN IF NOT EXISTS dernier_service DATE,
            ADD COLUMN IF NOT EXISTS prochaine_vidange DATE,
            ADD COLUMN IF NOT EXISTS localisation VARCHAR(150)
    """))
print("✓ Colonnes à jour.")

db = SessionLocal()
try:
    if not db.query(User).first():
        db.add(User(
            username="admin",
            full_name="Administrateur",
            hashed_password=hash_password("admin123"),
            is_active=True,
            role="ADMIN",
        ))
        db.commit()
        print("✓ Utilisateur admin créé (admin / admin123).")
    else:
        print("✓ Utilisateur admin déjà existant.")
finally:
    db.close()

print("→ Démarrage du serveur...")
