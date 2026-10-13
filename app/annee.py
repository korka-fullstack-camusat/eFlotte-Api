"""
Données annuelles : chaque fichier importé correspond à une année.

- Les modèles « annuels » héritent de `Annuel` et ont une colonne `annee`.
- L'année consultée arrive dans le paramètre `?annee=` de chaque requête (le front
  l'ajoute automatiquement) ; elle est rangée dans `annee_courante` (contextvar,
  propre à chaque requête).
- Toute lecture d'un modèle annuel est alors filtrée sur cette année (événement
  `do_orm_execute`) : listes, totaux, KPIs, graphiques et exports, sans modifier
  chaque route. Sans `?annee=`, rien n'est filtré (comportement d'origine).
- Une ligne créée prend l'année consultée (ou l'année civile en cours).
"""
import contextvars
import datetime

from fastapi import Request
from sqlalchemy import Column, Integer, event
from sqlalchemy.orm import Session, with_loader_criteria

annee_courante: contextvars.ContextVar[int | None] = contextvars.ContextVar("annee_courante", default=None)

ANNEE_MIN, ANNEE_MAX = 2015, 2100


def annee_par_defaut() -> int:
    return annee_courante.get() or datetime.date.today().year


def colonne_annee() -> Column:
    return Column(Integer, index=True, nullable=True, default=annee_par_defaut)


class Annuel:
    """Mixin des modèles dont les données sont rangées par année (colonne `annee`).
    La colonne est déclarée ici aussi : le filtre `with_loader_criteria(Annuel, …)`
    évalue `Annuel.annee` avant de l'appliquer à chaque modèle."""
    annee = colonne_annee()


@event.listens_for(Session, "do_orm_execute")
def _filtrer_par_annee(state):
    annee = annee_courante.get()
    if annee is None or not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    state.statement = state.statement.options(
        with_loader_criteria(Annuel, lambda cls: cls.annee == annee, include_aliases=True)
    )


def lire_annee(valeur) -> int | None:
    try:
        annee = int(str(valeur).strip())
    except (TypeError, ValueError):
        return None
    return annee if ANNEE_MIN <= annee <= ANNEE_MAX else None


async def definir_annee_requete(request: Request) -> None:
    """Dépendance globale (async : exécutée dans le contexte de la requête, puis
    copié vers la route) — lit `?annee=`."""
    annee_courante.set(lire_annee(request.query_params.get("annee")))


def remplacer_annee(db: Session, modele, annee: int) -> int:
    """Supprime les lignes de `annee` avant le réimport du fichier de cette année."""
    return db.query(modele).filter(modele.annee == annee).delete(synchronize_session=False)
