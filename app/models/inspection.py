from sqlalchemy import Column, Integer, String, Date, DateTime, Text, JSON, LargeBinary, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class RapportInspection(Base):
    """Checklist inspection / restitution d'un véhicule envoyée depuis l'app mobile chauffeur
    (formulaire CGR 06.01.02.02.000-FRM)."""
    __tablename__ = "rapports_inspection"

    id                = Column(Integer, primary_key=True, index=True)
    # SET NULL : supprimer un compte ne supprime pas l'historique des checklists
    user_id           = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    type_rapport      = Column(String(20), nullable=False, default="INSPECTION")  # INSPECTION | RESTITUTION
    date_rapport      = Column(Date, index=True, nullable=False)
    immatriculation   = Column(String(30), index=True, nullable=False)
    marque            = Column(String(100), nullable=True)
    modele            = Column(String(100), nullable=True)
    filiale           = Column(String(150), nullable=True)
    nom_chauffeur     = Column(String(150), nullable=False)
    kilometrage       = Column(Integer, nullable=False)
    visite_technique  = Column(Date, nullable=True)
    # {"items": {cle: {"valeur": "O"|"N"|"HAUT"|"BAS"|"S"|"NS", "commentaire": str|None}},
    #  "autres": {cle_section: str}}
    reponses          = Column(JSON, nullable=False, default=dict)
    commentaires      = Column(Text, nullable=True)
    nom_instructeur   = Column(String(150), nullable=True)   # restitution uniquement
    signature         = Column(Text, nullable=True)          # PNG en data URL
    nb_non_conformes  = Column(Integer, nullable=False, default=0)
    nb_critiques      = Column(Integer, nullable=False, default=0)  # points critiques non conformes
    created_at        = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class PhotoInspection(Base):
    __tablename__ = "rapports_inspection_photos"

    id           = Column(Integer, primary_key=True, index=True)
    rapport_id   = Column(Integer, ForeignKey("rapports_inspection.id", ondelete="CASCADE"), index=True, nullable=False)
    position     = Column(String(30), nullable=False)   # DEVANT | ARRIERE | GAUCHE | DROITE | INTERIEUR_AVANT | INTERIEUR_ARRIERE
    content_type = Column(String(50), nullable=False)
    data         = Column(LargeBinary, nullable=False)


class RelanceChecklist(Base):
    """Rappel envoyé à un chauffeur ; affiché dans son app jusqu'à son prochain envoi."""
    __tablename__ = "relances_checklist"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    envoye_par  = Column(String(150), nullable=True)
    message     = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    resolue_at  = Column(DateTime(timezone=True), nullable=True)
