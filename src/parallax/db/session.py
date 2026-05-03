from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from parallax.config import settings


def _build_engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def session_scope():
    """Yield a session; roll back on exception, close always."""
    session = _open_session_with_retry()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _open_session_with_retry():
    global engine, SessionLocal
    session = SessionLocal()
    try:
        session.connection()
        return session
    except OperationalError:
        session.close()
        engine.dispose()
        engine = _build_engine()
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        retry_session = SessionLocal()
        retry_session.connection()
        return retry_session
