"""
Ajout à la flotte des véhicules d'un export Excel absents de la base.

Fichier attendu : l'export « Camusat_Senegal_vehicles_AAAA.MM.JJ.xlsx »
(colonnes Brand, Model, Reg. № ; en-têtes cherchés dans les premières lignes).

  - Aucun véhicule existant n'est modifié ni supprimé (ils peuvent être
    attribués à des comptes chauffeurs).
  - Les plaques sont comparées sans espaces ni tirets, en majuscules.
  - Les lignes de test (« TEST » dans la plaque ou le modèle) sont ignorées.
"""
from typing import IO

import openpyxl
from sqlalchemy.orm import Session

from ..models.vehicule import Vehicule
from .attribution import cle_plaque

COL_PLAQUE = "reg. №"
COL_MARQUE = "brand"
COL_MODELE = "model"


class FichierInvalide(ValueError):
    pass


def nettoyer(val) -> str:
    """Texte sans espaces insécables ni espaces multiples."""
    return " ".join(str(val or "").replace("\xa0", " ").split())


def lire_excel(source: str | IO[bytes]) -> list[dict]:
    """Lignes {plaque, marque, modele} du fichier (chemin ou fichier binaire)."""
    try:
        ws = openpyxl.load_workbook(source, read_only=True, data_only=True).active
        lignes = list(ws.iter_rows(values_only=True))
    except Exception:
        raise FichierInvalide("Fichier illisible : utilisez l'export Excel des véhicules (.xlsx).")

    # Ligne d'en-têtes : la première qui contient « Reg. № »
    for i, ligne in enumerate(lignes[:20]):
        entetes = [nettoyer(c).lower() for c in ligne]
        if COL_PLAQUE in entetes:
            break
    else:
        raise FichierInvalide("Colonne « Reg. № » introuvable dans le fichier.")

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


def ajouter_manquants(db: Session, lignes: list[dict], appliquer: bool) -> dict:
    """Compare le fichier à la base ; avec appliquer=True, ajoute les manquants."""
    connues = {cle_plaque(p) for (p,) in db.query(Vehicule.plaque_immatriculation)}

    a_ajouter, ignores, vues = [], [], set()
    for l in lignes:
        cle = cle_plaque(l["plaque"])
        if "TEST" in l["plaque"] or "TEST" in (l["modele"] or "").upper():
            ignores.append({"plaque": l["plaque"], "raison": "Ligne de test"})
        elif cle in connues:
            continue
        elif cle in vues:
            ignores.append({"plaque": l["plaque"], "raison": "En double dans le fichier"})
        else:
            vues.add(cle)
            a_ajouter.append(l)

    if appliquer and a_ajouter:
        db.add_all(Vehicule(plaque_immatriculation=l["plaque"], marque=l["marque"], modele=l["modele"])
                   for l in a_ajouter)
        db.commit()

    return {
        "en_base": len(connues),
        "dans_fichier": len(lignes),
        "deja_en_base": len(lignes) - len(a_ajouter) - len(ignores),
        "manquants": a_ajouter,
        "ignores": ignores,
        "ajoutes": len(a_ajouter) if appliquer else 0,
    }
