from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # évite les connexions mortes après suspension de la base (ex: Neon autosuspend)
    pool_recycle=300,
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_connection, connection_record):
    # Certains poolers (ex: Neon) ne respectent pas search_path à la connexion
    # et ne supportent pas le paramètre de démarrage "options" — on le fixe ici.
    cursor = dbapi_connection.cursor()
    cursor.execute("SET search_path TO public")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
