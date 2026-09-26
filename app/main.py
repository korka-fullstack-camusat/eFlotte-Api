import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from .routers import (
    auth, vehicules, couts, entretiens, entretiens_bis, missions_chauffeur,
    suivi_devis, checklists_vl, suivi_pannes, pneumatiques,
    import_global, suivi_sinistres, carburant, inspections,
)


class _HealthCheckFilter(logging.Filter):
    """Masque /health des logs d'accès (appelé toutes les 10 s par Docker et Render)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        path = str(args[2]).split("?")[0] if isinstance(args, tuple) and len(args) >= 3 else ""
        return path not in ("/health", "/api/health")


logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())

app = FastAPI(
    title="eFlotte — Camusat Sénégal",
    description="Gestion de la flotte automobile — suivi global, coûts, entretiens, pannes",
    version="1.0.0",
)

app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(vehicules.router)
app.include_router(couts.router)
app.include_router(entretiens.router)
app.include_router(entretiens_bis.router)
app.include_router(missions_chauffeur.router)
app.include_router(suivi_devis.router)
app.include_router(checklists_vl.router)
app.include_router(suivi_pannes.router)
app.include_router(pneumatiques.router)
app.include_router(import_global.router)
app.include_router(suivi_sinistres.router)
app.include_router(carburant.router)
app.include_router(inspections.router)


@app.get("/")
def root():
    return {"message": "eFlotte API — OK", "docs": "/docs"}


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}
