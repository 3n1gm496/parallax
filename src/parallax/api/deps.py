from __future__ import annotations
from typing import Generator
from sqlalchemy.orm import Session
from parallax.db.session import SessionLocal


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
