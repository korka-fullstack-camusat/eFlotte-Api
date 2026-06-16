from sqlalchemy import Column, Integer, String, Boolean
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String, unique=True, index=True, nullable=False)
    full_name       = Column(String, nullable=True)
    email           = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active       = Column(Boolean, default=True)
    # Rôle : ADMIN (gestion complète + utilisateurs), EDITOR (lecture/écriture), VIEWER (lecture seule)
    role            = Column(String(20), nullable=False, default="EDITOR")
