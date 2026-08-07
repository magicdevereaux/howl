from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session, rolling back before it is returned.

    The rollback matters: a request that raises partway through a unit of work
    (an IntegrityError, an HTTPException after a flush) leaves the session with
    pending changes and an open transaction. Without an explicit rollback the
    connection goes back to the pool dirty, and the next request to pick it up
    can commit the previous one's half-written state.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
