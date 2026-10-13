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
    RapportInspection, PhotoInspection, RelanceChecklist,
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
    # (Les anciennes corrections automatiques du mois et de l'année du carburant,
    #  rejouées à chaque démarrage, sont supprimées : elles déplaçaient les données
    #  2025 en 2026. Les imports rangent désormais l'année choisie et le mois de
    #  chaque ligne — voir app/annee.py.)
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
    # User — véhicule attribué (rôle CHAUFFEUR)
    conn.execute(sqlalchemy.text("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS vehicule_plaque VARCHAR(30),
            ADD COLUMN IF NOT EXISTS filiale VARCHAR(150),
            ADD COLUMN IF NOT EXISTS telephone VARCHAR(30),
            ADD COLUMN IF NOT EXISTS doit_changer_mdp BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS identifiants_envoyes_at TIMESTAMPTZ
    """))
print("✓ Colonnes à jour.")

print("→ Données annuelles (colonne annee)...")
# Table → expression donnant l'année des lignes existantes (sinon l'année en cours)
ANNUELLES = {
    "missions_chauffeur":      "EXTRACT(YEAR FROM date)",
    "suivi_devis":             "EXTRACT(YEAR FROM date)",
    "suivi_pannes":            "EXTRACT(YEAR FROM COALESCE(date, date_indisponibilite))",
    "suivi_sinistres":         "EXTRACT(YEAR FROM COALESCE(date_sinistre, date_declaration))",
    "pneumatiques":            "EXTRACT(YEAR FROM date_prevue)",
    "couts_flotte":            "EXTRACT(YEAR FROM mois)",
    "checklists_vl":           "NULL",
    "entretiens_vehicule":     "NULL",
    "entretiens_vehicule_bis": "NULL",
}
with engine.begin() as conn:
    annee_en_cours = _dt.date.today().year
    for table, expr in ANNUELLES.items():
        conn.execute(sqlalchemy.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS annee INTEGER"))
        conn.execute(sqlalchemy.text(
            f"UPDATE {table} SET annee = COALESCE({expr}, {annee_en_cours}) WHERE annee IS NULL"
        ))
        conn.execute(sqlalchemy.text(f"CREATE INDEX IF NOT EXISTS ix_{table}_annee ON {table} (annee)"))
    # Une ligne par véhicule ET par année (au lieu d'une ligne par véhicule)
    for table, nom in (("checklists_vl", "uq_checklists_vl_plaque_annee"),
                       ("entretiens_vehicule", "uq_entretiens_vehicule_plaque_annee"),
                       ("entretiens_vehicule_bis", "uq_entretiens_bis_plaque_annee")):
        conn.execute(sqlalchemy.text(f"DROP INDEX IF EXISTS ix_{table}_plaque_immatriculation"))
        conn.execute(sqlalchemy.text(f"CREATE INDEX IF NOT EXISTS ix_{table}_plaque_immatriculation ON {table} (plaque_immatriculation)"))
        conn.execute(sqlalchemy.text(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{nom}') THEN
                    ALTER TABLE {table} ADD CONSTRAINT {nom} UNIQUE (plaque_immatriculation, annee);
                END IF;
            END $$;
        """))
print("✓ Données annuelles prêtes.")

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
