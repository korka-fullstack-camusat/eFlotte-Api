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
    Pneumatique, SuiviSinistre, ImportGlobalLog, Carburant, RecapPanneVehicule,
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
            ADD COLUMN IF NOT EXISTS type_carburant VARCHAR(20),
            ADD COLUMN IF NOT EXISTS chauffeur VARCHAR(150),
            ADD COLUMN IF NOT EXISTS kilometrage INTEGER,
            ADD COLUMN IF NOT EXISTS dernier_service DATE,
            ADD COLUMN IF NOT EXISTS prochaine_vidange DATE,
            ADD COLUMN IF NOT EXISTS localisation VARCHAR(150)
    """))
    conn.execute(sqlalchemy.text("""
        ALTER TABLE carburant
            ADD COLUMN IF NOT EXISTS mois INTEGER NOT NULL DEFAULT 1
    """))
    import datetime as _dt
    current_year = _dt.date.today().year
    conn.execute(sqlalchemy.text(f"""
        ALTER TABLE carburant
            ADD COLUMN IF NOT EXISTS annee INTEGER NOT NULL DEFAULT {current_year}
    """))
    # Corriger le mois depuis dernier_plein pour les lignes avec DEFAULT 1
    conn.execute(sqlalchemy.text("""
        UPDATE carburant
        SET mois = EXTRACT(MONTH FROM dernier_plein)::INTEGER
        WHERE dernier_plein IS NOT NULL
          AND mois = 1
          AND EXTRACT(MONTH FROM dernier_plein) != 1
    """))
    # Rapatrier les lignes qui ont l'ancien default (2025) vers l'année courante
    conn.execute(sqlalchemy.text(f"""
        UPDATE carburant SET annee = {current_year} WHERE annee = 2025
    """))
    # Corriger l'année depuis dernier_plein pour les lignes avec DEFAULT année courante
    conn.execute(sqlalchemy.text(f"""
        UPDATE carburant
        SET annee = EXTRACT(YEAR FROM dernier_plein)::INTEGER
        WHERE dernier_plein IS NOT NULL
          AND annee = {current_year}
          AND EXTRACT(YEAR FROM dernier_plein) BETWEEN 2015 AND {current_year + 1}
          AND EXTRACT(YEAR FROM dernier_plein) != {current_year}
    """))
    # SuiviPanne — statut
    conn.execute(sqlalchemy.text("""
        ALTER TABLE suivi_pannes
            ADD COLUMN IF NOT EXISTS statut VARCHAR(50) DEFAULT 'EN_COURS'
    """))
    # MissionChauffeur — motif + heures
    conn.execute(sqlalchemy.text("""
        ALTER TABLE missions_chauffeur
            ADD COLUMN IF NOT EXISTS motif VARCHAR(255),
            ADD COLUMN IF NOT EXISTS heure_debut TIME,
            ADD COLUMN IF NOT EXISTS heure_fin TIME
    """))
    # RecapPanneVehicule — sorti
    conn.execute(sqlalchemy.text("""
        ALTER TABLE recap_pannes_vehicules
            ADD COLUMN IF NOT EXISTS sorti BOOLEAN NOT NULL DEFAULT FALSE
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
