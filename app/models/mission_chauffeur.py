from sqlalchemy import Column, Integer, String, Date, Text
from ..database import Base


class MissionChauffeur(Base):
    """Missions des chauffeurs des pôles — issu de la feuille 'CHAUFFEUR POLES'."""
    __tablename__ = "missions_chauffeur"

    id              = Column(Integer, primary_key=True, index=True)
    date            = Column(Date, index=True, nullable=False)
    immatriculation = Column(String(30), index=True, nullable=False)
    chauffeur       = Column(String(150), nullable=True)
    demandeur       = Column(String(150), nullable=True)
    telephone       = Column(String(30), nullable=True)
    projet          = Column(String(150), nullable=True)
    destination     = Column(String(255), nullable=True)
    date_depart     = Column(Date, nullable=True)
    date_retour     = Column(Date, nullable=True)
    commentaires    = Column(Text, nullable=True)
