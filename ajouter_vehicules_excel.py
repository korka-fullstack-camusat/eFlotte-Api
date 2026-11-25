"""
Ajoute à la flotte les véhicules d'un export Excel qui n'existent pas encore en base.
(Même traitement que le bouton « Mettre à jour les véhicules » de la page Comptes
utilisateurs ; voir app/services/import_vehicules.py.)

Par défaut le script affiche seulement ce qu'il ajouterait. Pour écrire en base :

    docker cp Camusat_Senegal_vehicles_2026.11.24.xlsx eflotte-api:/tmp/vehicules.xlsx
    docker exec -it eflotte-api python ajouter_vehicules_excel.py /tmp/vehicules.xlsx            # aperçu
    docker exec -it eflotte-api python ajouter_vehicules_excel.py /tmp/vehicules.xlsx --appliquer
"""
import argparse
import sys

from app.database import SessionLocal
from app.services.import_vehicules import FichierInvalide, ajouter_manquants, lire_excel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fichier", help="export Excel des véhicules (.xlsx)")
    parser.add_argument("--appliquer", action="store_true", help="écrire en base (sinon : aperçu seulement)")
    args = parser.parse_args()

    try:
        lignes = lire_excel(args.fichier)
    except FichierInvalide as e:
        sys.exit(str(e))

    db = SessionLocal()
    try:
        r = ajouter_manquants(db, lignes, args.appliquer)
    finally:
        db.close()

    print(f"Véhicules en base : {r['en_base']} — lignes dans le fichier : {r['dans_fichier']}")
    print(f"Déjà en base : {r['deja_en_base']}")
    for i in r["ignores"]:
        print(f"  ignoré : {i['plaque']} ({i['raison'].lower()})")
    print(f"Manquants : {len(r['manquants'])}")
    for l in r["manquants"]:
        print(f"  + {l['plaque']:<12} {l['marque'] or '':<14} {l['modele'] or ''}")

    if r["ajoutes"]:
        print(f"\n{r['ajoutes']} véhicule(s) ajouté(s).")
    elif r["manquants"]:
        print("\nAperçu seulement : relancer avec --appliquer pour les ajouter.")


if __name__ == "__main__":
    main()
