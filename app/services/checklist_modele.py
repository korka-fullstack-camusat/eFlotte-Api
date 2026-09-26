"""
Contenu exact du formulaire papier « CHECKLIST INSPECTION/RESTITUTION D'UN VÉHICULE »
(CGR 06.01.02.02.000-FRM, V0.2024.02.01) — source unique pour l'app mobile et le dashboard.

`critique=True` = points « en gras-italique-souligné » du formulaire : à vérifier
quotidiennement, un point non conforme entraîne l'immobilisation immédiate du véhicule.
"""

# Types de réponse : (valeur, libellé) ; la valeur `negative` est la non-conformité.
TYPES_REPONSE = {
    "OUI_NON": {"options": [("O", "Oui"), ("N", "Non")], "negative": "N"},
    "NIVEAU":  {"options": [("HAUT", "Haut"), ("BAS", "Bas")], "negative": "BAS"},
    "ETAT":    {"options": [("S", "Satisfaisant"), ("NS", "Non satisfaisant")], "negative": "NS"},
}

SECTIONS = [
    {
        "cle": "documents",
        "titre": "Certificats et assurances",
        "question": "Fournis ?",
        "type": "OUI_NON",
        "items": [
            ("certificat_assurance", "Certificat d'assurance", True),
            ("manuel_utilisation", "Manuel d'utilisation véhicule", False),
            ("carte_grise", "Carte grise", False),
            ("controle_technique", "Contrôle technique", False),
            ("permis_conduire", "Permis de conduire chauffeur", True),
            ("livret_entretien", "Livret d'entretien à jour", False),
            ("lettre_mission", "Lettre de mission chauffeur", False),
        ],
    },
    {
        "cle": "equipement",
        "titre": "Équipement",
        "question": "Fourni ?",
        "type": "OUI_NON",
        "items": [
            ("roue_secours", "Roue de secours ou bombe anti-crevaison", True),
            ("alarme_recul", "Alarme de recul", True),
            ("klaxon", "Klaxon", True),
            ("tapis_caoutchouc", "Tapis en caoutchouc", False),
            ("pompe_manometre", "Pompe avec manomètre", False),
            ("cric", "Cric", True),
            ("boite_outils", "Boîte à outils", False),
            ("cable_demarrage", "Câble de démarrage et pinces", False),
            ("cale", "Cale", False),
            ("chaine_remorquage", "Chaîne de remorquage", False),
            ("air_conditionne", "Air conditionné", False),
        ],
    },
    {
        "cle": "niveaux",
        "titre": "Niveaux",
        "question": "Niveau",
        "type": "NIVEAU",
        "items": [
            ("carburant", "Carburant", True),
            ("liquide_refroidissement", "Liquide de refroidissement", False),
            ("huile", "Huile", False),
            ("lave_glace", "Lave-glace", True),
        ],
    },
    {
        "cle": "securite",
        "titre": "Équipements de sécurité",
        "question": "Fourni ?",
        "type": "OUI_NON",
        "items": [
            ("extincteur", "Extincteur à poudre", False),
            ("trousse_secours", "Trousse de 1er secours", True),
            ("gilet", "Gilet réfléchissant", False),
            ("torche", "Torche (batterie chargée)", False),
            ("pelle", "Pelle", False),
            ("gants", "Gants", False),
            ("triangle", "Triangle de signalisation", False),
        ],
    },
    {
        "cle": "etat",
        "titre": "État du véhicule",
        "question": "État",
        "type": "ETAT",
        "items": [
            ("carrosserie", "Carrosserie", False),
            ("retroviseurs", "Rétroviseurs", True),
            ("essuie_glace", "Essuie-glace", True),
            ("pneus", "Pneus (+ pneu de secours)", True),
            ("clignotants", "Feux de clignotants", True),
            ("feux", "Feux (+ feu de recul)", True),
            ("interieur", "Intérieur (propreté)", False),
            ("ceinture", "Ceinture de sécurité", True),
            ("appuie_tete", "Appuie-tête", True),
            ("pare_brise", "Pare-brise et fenêtres", True),
        ],
    },
]

PHOTOS = [
    ("DEVANT", "Devant"),
    ("ARRIERE", "Arrière"),
    ("GAUCHE", "Côté gauche"),
    ("DROITE", "Côté droit"),
    ("INTERIEUR_AVANT", "Intérieur (avant)"),
    ("INTERIEUR_ARRIERE", "Intérieur (arrière)"),
]

TYPES_RAPPORT = [("INSPECTION", "Inspection"), ("RESTITUTION", "Restitution")]

# Index : clé d'item → (section, libellé, critique, type de réponse)
ITEMS = {
    cle: {"section": s["cle"], "libelle": libelle, "critique": critique, "type": s["type"]}
    for s in SECTIONS
    for cle, libelle, critique in s["items"]
}


def modele_public() -> dict:
    """Version JSON du modèle envoyée au front."""
    return {
        "types_reponse": {
            t: {"options": [{"valeur": v, "libelle": l} for v, l in d["options"]], "negative": d["negative"]}
            for t, d in TYPES_REPONSE.items()
        },
        "sections": [
            {
                "cle": s["cle"], "titre": s["titre"], "question": s["question"], "type": s["type"],
                "items": [{"cle": c, "libelle": l, "critique": cr} for c, l, cr in s["items"]],
            }
            for s in SECTIONS
        ],
        "photos": [{"position": p, "libelle": l} for p, l in PHOTOS],
        "types_rapport": [{"valeur": v, "libelle": l} for v, l in TYPES_RAPPORT],
    }


def est_non_conforme(cle: str, valeur: str) -> bool:
    return TYPES_REPONSE[ITEMS[cle]["type"]]["negative"] == valeur


def valider_reponses(reponses: dict) -> tuple[dict, int, int]:
    """Vérifie que chaque point a une réponse valide.
    Retourne (réponses nettoyées, nb non conformes, nb critiques non conformes).
    Lève ValueError avec un message lisible sinon."""
    items_in = (reponses or {}).get("items") or {}
    autres_in = (reponses or {}).get("autres") or {}
    items_out: dict = {}
    manquants = []
    nb_nc = nb_crit = 0
    for cle, info in ITEMS.items():
        rep = items_in.get(cle) or {}
        valeur = rep.get("valeur")
        valides = [v for v, _ in TYPES_REPONSE[info["type"]]["options"]]
        if valeur not in valides:
            manquants.append(info["libelle"])
            continue
        commentaire = (rep.get("commentaire") or "").strip()[:500] or None
        items_out[cle] = {"valeur": valeur, "commentaire": commentaire}
        if est_non_conforme(cle, valeur):
            nb_nc += 1
            if info["critique"]:
                nb_crit += 1
    if manquants:
        raise ValueError("Points sans réponse : " + ", ".join(manquants))
    sections = {s["cle"] for s in SECTIONS}
    autres_out = {
        k: str(v).strip()[:500] for k, v in autres_in.items() if k in sections and str(v or "").strip()
    }
    return {"items": items_out, "autres": autres_out}, nb_nc, nb_crit
