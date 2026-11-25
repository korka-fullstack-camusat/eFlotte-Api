"""
Ajoute à la flotte les véhicules d'un export Excel qui n'existent pas encore en base.

Le fichier attendu est l'export « Camusat_Senegal_vehicles_AAAA.MM.JJ.xlsx »
(colonnes Brand, Model, Reg. №, Label, Car Group ; en-têtes cherchés dans les
premières lignes).

  - Aucun véhicule existant n'est modifié ni supprimé (ils peuvent être
    attribués à des comptes chauffeurs).
  - Les plaques sont comparées sans espaces ni tirets, en majuscules
    (« AA-512-YS » = « aa 512 ys »).
  - Les lignes de test (« TEST » dans la plaque ou le modèle) sont ignorées.

Par défaut le script affiche seulement ce qu'il ajouterait. Pour écrire en base :

    docker cp Camusat_Senegal_vehicles_2026.11.24.xlsx eflotte-api:/tmp/vehicules.xlsx
    docker exec -it eflotte-api python ajouter_vehicules_excel.py /tmp/vehicules.xlsx            # aperçu
    docker exec -it eflotte-api python ajouter_vehicules_excel.py /tmp/vehicules.xlsx --appliquer
"""
import argparse
import sys

import openpyxl

from app.database import SessionLocal
from app.models.vehicule import Vehicule
from app.services.attribution import cle_plaque

COL_PLAQUE = "reg. №"
COL_MARQUE = "brand"
COL_MODELE = "model"


def nettoyer(val) -> str:
    """Texte sans espaces insécables ni espaces multiples."""
    return " ".join(str(val or "").replace("\xa0", " ").split())


def lire_excel(chemin: str) -> list[dict]:
    ws = openpyxl.load_workbook(chemin, read_only=True, data_only=True).active
    lignes = list(ws.iter_rows(values_only=True))

    # Ligne d'en-têtes : la première qui contient « Reg. № »
    for i, ligne in enumerate(lignes[:20]):
        entetes = [nettoyer(c).lower() for c in ligne]
        if COL_PLAQUE in entetes:
            break
    else:
        sys.exit(f"Colonne « Reg. № » introuvable dans {chemin}.")

    idx = {nom: entetes.index(nom) if nom in entetes else None
           for nom in (COL_PLAQUE, COL_MARQUE, COL_MODELE)}

    def cell(ligne, nom):
        j = idx[nom]
        return nettoyer(ligne[j]) if j is not None and j < len(ligne) else ""

    return [
        {"plaque": cell(l, COL_PLAQUE).upper(),
         "marque": cell(l, COL_MARQUE).upper() or None,
         "modele": cell(l, COL_MODELE) or None}
        for l in lignes[i + 1:]
        if cell(l, COL_PLAQUE)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fichier", help="export Excel des véhicules (.xlsx)")
    parser.add_argument("--appliquer", action="store_true", help="écrire en base (sinon : aperçu seulement)")
    args = parser.parse_args()

    lignes = lire_excel(args.fichier)

    db = SessionLocal()
    try:
        connues = {cle_plaque(p) for (p,) in db.query(Vehicule.plaque_immatriculation)}
        print(f"Véhicules en base : {len(connues)} — lignes dans le fichier : {len(lignes)}")

        a_ajouter, ignores, vues = [], [], set()
        for l in lignes:
            cle = cle_plaque(l["plaque"])
            if "TEST" in l["plaque"] or "TEST" in (l["modele"] or "").upper():
                ignores.append(f"{l['plaque']} (ligne de test)")
            elif cle in connues:
                continue
            elif cle in vues:
                ignores.append(f"{l['plaque']} (en double dans le fichier)")
            else:
                vues.add(cle)
                a_ajouter.append(l)

        print(f"Déjà en base : {len(lignes) - len(a_ajouter) - len(ignores)}")
        for msg in ignores:
            print(f"  ignoré : {msg}")
        print(f"À ajouter : {len(a_ajouter)}")
        for l in a_ajouter:
            print(f"  + {l['plaque']:<12} {l['marque'] or '':<14} {l['modele'] or ''}")

        if not a_ajouter:
            return
        if not args.appliquer:
            print("\nAperçu seulement : relancer avec --appliquer pour les ajouter.")
            return

        db.add_all(Vehicule(plaque_immatriculation=l["plaque"], marque=l["marque"], modele=l["modele"])
                   for l in a_ajouter)
        db.commit()
        print(f"\n{len(a_ajouter)} véhicule(s) ajouté(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
