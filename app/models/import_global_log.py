from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from ..database import Base


class ImportGlobalLog(Base):
    """Historique des imports globaux."""
    __tablename__ = "import_global_logs"

    id         = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    username   = Column(String(100), nullable=True)
    filename   = Column(String(500), nullable=True)
    results    = Column(JSON, nullable=False)          # dict SectionResult par rubrique
    total_created = Column(Integer, default=0)
    total_updated = Column(Integer, default=0)
    total_errors  = Column(Integer, default=0)
