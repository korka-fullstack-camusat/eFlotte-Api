"""
Téléchargements publics : APK de l'application mobile (page /app du site).
Les fichiers sont lus dans le dossier telechargements/ du projet (ou TELECHARGEMENTS_DIR).
Utile quand le site n'est pas derrière Caddy (API uvicorn + serveur Vite) ; derrière
Caddy, celui-ci sert le même dossier directement.
"""
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["Téléchargements"])

DOSSIER = Path(os.getenv("TELECHARGEMENTS_DIR") or Path(__file__).resolve().parents[2] / "telechargements").resolve()
TYPES = {".apk": "application/vnd.android.package-archive"}


@router.api_route("/telechargements/{nom}", methods=["GET", "HEAD"], include_in_schema=False)
def telecharger(nom: str):
    chemin = (DOSSIER / nom).resolve()
    # Uniquement un fichier du dossier lui-même (pas de ../, pas de fichiers cachés)
    if chemin.parent != DOSSIER or nom.startswith(".") or chemin.suffix.lower() not in TYPES or not chemin.is_file():
        raise HTTPException(404, "Fichier introuvable")
    return FileResponse(
        chemin,
        media_type=TYPES[chemin.suffix.lower()],
        filename="eFlotte-Camusat.apk" if chemin.suffix.lower() == ".apk" else chemin.name,
        # Content-Encoding identity : pas de compression gzip (APK déjà compressé, taille connue)
        headers={"Cache-Control": "no-cache", "Content-Encoding": "identity"},
    )
