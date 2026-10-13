"""
Lecture de la feuille CARBURANT d'un fichier annuel (tableau de bord flotte ou
export carburant) et remplacement des données carburant de l'année.

Formats acceptés :
  - tableau de bord : une ligne de mois au-dessus des en-têtes, puis un ou
    plusieurs blocs côte à côte qui commencent chacun par une colonne « Matricule »
    (un bloc = l'export d'un mois) ;
  - export simple : une ligne d'en-têtes, avec éventuellement une colonne
    « Période » (AAAA-MM) ou « Mois » donnant le mois de chaque ligne.

Mois d'une ligne : « Période » / « Mois » (ou à défaut son « DernierPlein ») si la
colonne existe ; sinon le bloc est un mois entier et prend le mois le plus fréquent
de ses « DernierPlein » (les lignes sans dernier plein, ex. camions, prennent le
mois de leur bloc).
"""
import re
from collections import Counter

import pandas as pd
from sqlalchemy.orm import Session

from ..annee import annee_courante, remplacer_annee
from ..models.carburant import Carburant

MOIS_NOMS = {"JAN": 1, "FEV": 2, "FÉV": 2, "FEB": 2, "MAR": 3, "AVR": 4, "APR": 4, "MAI": 5, "MAY": 5,
             "JUIN": 6, "JUN": 6, "JUIL": 7, "JUL": 7, "AOU": 8, "AOÛ": 8, "AUG": 8, "SEP": 9,
             "OCT": 10, "NOV": 11, "DEC": 12, "DÉC": 12}

# Champ en base → noms de colonnes acceptés (comparaison sans casse ni espaces de bord)
COLONNES = {
    "quantite_totale":  ("QuantiteTotale", "Litres consommés", "Litres"),
    "montant_total":    ("MontantTotal", "Montant TTC"),
    "mt_ht":            ("Mt HT", "Montant HT"),
    "prix_unitaire":    ("PrixUnitaire", "Prix unitaire"),
    "type_carburant":   ("Fuel type", "Type carburant", "TYPE", "CARBURANT"),
    "distance_totale":  ("DistanceTotale", "Distance déclarée retenue", "Distance déclarée"),
    "distance_gps":     ("Distance GPS",),
    "car_group":        ("CarGroup", "Car Group"),
    "dernier_plein":    ("DernierPlein", "Dernier plein"),
    "driver_name":      ("DriverName", "Conducteur(s) ayant pris le carburant", "Conducteur"),
    "nom_chauffeur":    ("Nom de chauffeur", "Label"),
    "code_projet":      ("CodeProjet", "Business Line(s)", "Business Line"),
    "num_carte":        ("NumCarte", "Numéro(s) carte Total", "Numéro carte"),
    "conso_100":        ("Conso/100 recommandée", "Conso/100 distance GPS", "Conso/100"),
    "vehicle_type":     ("Vehicle Type", "Type véhicule"),
    "dist_recommandee": ("Distance recommandée CO2", "Distance recommandée"),
    "periode":          ("Période", "Periode", "Mois"),
}
NUMERIQUES = {"quantite_totale", "montant_total", "mt_ht", "prix_unitaire", "distance_totale",
              "distance_gps", "conso_100", "dist_recommandee"}


def _vide(v) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _texte(v) -> str | None:
    if _vide(v):
        return None
    s = str(v).strip()
    return s if s and s.upper() not in ("NAN", "N/A", "NA", "NONE", "NAT") else None


def _nombre(v) -> float | None:
    if _vide(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date(v):
    if _vide(v):
        return None
    try:
        # « 2026-04-12 » (ISO) se lit année-mois-jour ; « 12/04/2026 » jour en premier
        iso = isinstance(v, str) and len(v.strip()) >= 8 and v.strip()[:4].isdigit()
        return pd.to_datetime(v, dayfirst=not iso).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _carte(v) -> str | None:
    if isinstance(v, float) and not pd.isna(v):
        return str(int(v))
    return _texte(v)


def _type_carburant(v) -> str | None:
    s = (_texte(v) or "").upper()
    if s in ("DIESEL", "GAZOIL", "GAZOLE", "GASOIL", "GO"):
        return "GAZOIL"
    if s in ("PETROL", "PETROL95", "ESSENCE", "SP95", "SP98", "SP", "SUPER"):
        return "ESSENCE"
    return s or None


def _periode(v) -> tuple[int | None, int | None]:
    """(mois, année ou None) depuis une date, « 2026-03 », « 03/2026 », « 3 » ou « Mars »."""
    if _vide(v):
        return None, None
    if hasattr(v, "month") and hasattr(v, "year"):
        return v.month, v.year
    t = str(v).strip().upper()
    m = re.match(r"^(\d{4})[-/](\d{1,2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(2)), int(m.group(1))
    m = re.match(r"^(\d{1,2})[-/](\d{4})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1)), int(m.group(2))
    if t.replace(".0", "").isdigit() and 1 <= int(float(t)) <= 12:
        return int(float(t)), None
    for nom in sorted(MOIS_NOMS, key=len, reverse=True):
        if t.startswith(nom):
            return MOIS_NOMS[nom], None
    return None, None


def feuille_carburant(xls: pd.ExcelFile) -> str | None:
    noms = [s for s in xls.sheet_names if "CARBURANT" in s.strip().upper()]
    return next((s for s in noms if s.strip().upper() == "CARBURANT"), noms[0] if noms else None)


def lire_carburant(brut: pd.DataFrame, annee: int) -> tuple[list[dict], list[dict], int]:
    """Lit la feuille (lue sans en-tête). Renvoie (lignes à enregistrer, erreurs,
    nombre de lignes d'une autre année)."""
    entete = next(
        (i for i in range(min(len(brut), 15))
         if any(str(v).strip().upper() == "MATRICULE" for v in brut.iloc[i].tolist())),
        None,
    )
    if entete is None:
        return [], [{"ligne": 1, "message": "Colonne « Matricule » introuvable"}], 0

    noms = [str(v).strip() if not _vide(v) else "" for v in brut.iloc[entete].tolist()]
    debuts = [j for j, n in enumerate(noms) if n.upper() == "MATRICULE"]
    lignes, erreurs, hors_annee = [], [], 0

    for b, debut in enumerate(debuts):
        fin = debuts[b + 1] if b + 1 < len(debuts) else len(noms)
        cols: dict[str, int] = {}
        for champ, alias in COLONNES.items():
            cibles = {a.upper() for a in alias}
            j = next((j for j in range(debut + 1, fin) if noms[j].upper() in cibles), None)
            if j is not None:
                cols[champ] = j
        donnees = brut.iloc[entete + 1:]
        if "type_carburant" not in cols:
            # Colonne type carburant sans en-tête (GAZOIL / ESSENCE)
            for j in range(debut + 1, fin):
                if not noms[j] and donnees.iloc[:, j].astype(str).str.strip().str.upper().isin(
                        ["GAZOIL", "ESSENCE", "DIESEL", "GASOIL"]).any():
                    cols["type_carburant"] = j
                    break

        a_lire = []
        for i in range(len(donnees)):
            matr = _texte(donnees.iat[i, debut])
            if not matr or any(k in matr.upper() for k in ("TOTAL", "MATRICULE")):
                continue
            a_lire.append((entete + 1 + i, matr))
        if not a_lire:
            continue

        # Mois du bloc : le plus fréquent des derniers pleins
        mois_bloc, annee_bloc = None, None
        if "dernier_plein" in cols:
            dates = [d for d in (_date(brut.iat[i, cols["dernier_plein"]]) for i, _ in a_lire) if d]
            if dates:
                (annee_bloc, mois_bloc), _n = Counter((d.year, d.month) for d in dates).most_common(1)[0]

        for i, matr in a_lire:
            val = lambda champ: brut.iat[i, cols[champ]] if champ in cols else None
            if "periode" in cols:
                # Une ligne par mois : Période de la ligne, sinon son propre dernier plein
                mois_l, annee_l = _periode(val("periode"))
                plein = _date(val("dernier_plein")) if not mois_l else None
                if plein:
                    mois_l, annee_l = plein.month, None
            else:
                # Bloc d'un seul mois (tableau de bord) : mois du bloc
                mois_l, annee_l = mois_bloc, annee_bloc
            if not mois_l:
                erreurs.append({"ligne": i + 1, "message": f"{matr} : mois introuvable (Période, Mois ou DernierPlein)"})
                continue
            if annee_l and annee_l != annee:
                hors_annee += 1
                continue
            ligne = {"matricule": matr, "mois": mois_l, "annee": annee}
            for champ in COLONNES:
                if champ == "periode" or champ not in cols:
                    continue
                v = val(champ)
                if champ in NUMERIQUES:
                    ligne[champ] = _nombre(v)
                elif champ == "dernier_plein":
                    ligne[champ] = _date(v)
                elif champ == "type_carburant":
                    ligne[champ] = _type_carburant(v)
                elif champ == "num_carte":
                    ligne[champ] = _carte(v)
                else:
                    ligne[champ] = _texte(v)
            lignes.append(ligne)

    return lignes, erreurs, hors_annee


def lire_recap_couts(brut: pd.DataFrame, annee: int, mois_exclus: set[int]) -> list[dict]:
    """Feuille « SUIVI GLOBALE DES COUTS » : une ligne par véhicule, colonnes
    « AAAA-MM_CARBURANT » (coût carburant HT) et « AAAA-MM_DISTANCE ». Sert pour les
    mois sans bloc détaillé dans la feuille CARBURANT. Litres, TTC et type de
    carburant n'y figurent pas : ils restent vides (jamais estimés)."""
    entete = next(
        (i for i in range(min(len(brut), 15))
         if any("IMMATRICULATION" in str(v).upper() for v in brut.iloc[i].tolist())),
        None,
    )
    if entete is None:
        return []
    noms = [str(v).strip().upper() if not _vide(v) else "" for v in brut.iloc[entete].tolist()]
    j_plaque = next(j for j, n in enumerate(noms) if "IMMATRICULATION" in n)
    j_type = next((j for j, n in enumerate(noms) if n == "TYPE VEHICULE"), None)
    colonnes: dict[int, dict[str, int]] = {}
    for j, n in enumerate(noms):
        m = re.match(r"^(\d{4})-(\d{2})_(CARBURANT|DISTANCE)$", n)
        if m and int(m.group(1)) == annee and 1 <= int(m.group(2)) <= 12 and int(m.group(2)) not in mois_exclus:
            colonnes.setdefault(int(m.group(2)), {})[m.group(3)] = j

    lignes = []
    for i in range(entete + 1, len(brut)):
        matr = _texte(brut.iat[i, j_plaque])
        if not matr or "TOTAL" in matr.upper():
            continue
        for mois, cols in colonnes.items():
            cout = _nombre(brut.iat[i, cols["CARBURANT"]]) if "CARBURANT" in cols else None
            if cout is None:
                continue
            lignes.append({
                "matricule": matr, "mois": mois, "annee": annee,
                "mt_ht": cout,
                "distance_totale": _nombre(brut.iat[i, cols["DISTANCE"]]) if "DISTANCE" in cols else None,
                "vehicle_type": _texte(brut.iat[i, j_type]) if j_type is not None else None,
            })
    return lignes


def feuille_recap_couts(xls: pd.ExcelFile) -> str | None:
    return next((s for s in xls.sheet_names if "SUIVI GLOBAL" in s.upper() and "COUT" in s.upper()), None)


def importer_carburant(db: Session, xls: pd.ExcelFile, annee: int, feuille: str | None = None) -> dict:
    """Remplace les données carburant de `annee` par la feuille CARBURANT du fichier
    (complétée par « SUIVI GLOBALE DES COUTS » pour les mois sans détail).
    Rien n'est supprimé si aucune ligne n'est exploitable. Ne fait pas le commit."""
    feuille = feuille or feuille_carburant(xls)
    if not feuille:
        return {"feuille": None, "created": 0, "updated": 0, "errors": [], "hors_annee": 0, "mois": [],
                "mois_detail": [], "mois_recap": []}
    lignes, erreurs, hors_annee = lire_carburant(xls.parse(feuille, header=None), annee)
    mois_detail = {l["mois"] for l in lignes}
    # Mois sans bloc détaillé : coût HT et distance du suivi global des coûts
    recap = feuille_recap_couts(xls)
    lignes_recap = lire_recap_couts(xls.parse(recap, header=None), annee, mois_detail) if recap else []
    lignes += lignes_recap
    res = {"feuille": feuille, "created": 0, "updated": 0, "errors": erreurs,
           "hors_annee": hors_annee, "mois": sorted({l["mois"] for l in lignes}),
           "mois_detail": sorted(mois_detail), "mois_recap": sorted({l["mois"] for l in lignes_recap})}
    if not lignes:
        return res

    remplacer_annee(db, Carburant, annee)
    annee_courante.set(annee)
    # Un même véhicule peut avoir une ligne GAZOIL et une ligne ESSENCE (cartes différentes)
    vues: dict[tuple, Carburant] = {}
    for l in lignes:
        cle = (l["matricule"], l["mois"], l.get("type_carburant"), l.get("num_carte"))
        if cle in vues:
            for k, v in l.items():
                setattr(vues[cle], k, v)
            res["updated"] += 1
        else:
            vues[cle] = Carburant(**l)
            db.add(vues[cle])
            res["created"] += 1
    return res
