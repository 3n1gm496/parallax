from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from parallax.db.models import Base
from parallax.config import settings


def _default_test_database_url() -> str:
    return settings.test_database_url


def _test_database_url() -> str:
    return os.getenv("TEST_DATABASE_URL") or _default_test_database_url()


def _db_reachable() -> bool:
    try:
        engine = create_engine(_test_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_db():
    if not _db_reachable():
        raise RuntimeError(f"postgres_test not reachable at {_test_database_url()}")


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(_test_database_url(), pool_pre_ping=True)
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def test_session(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        yield session
        session.rollback()
    finally:
        session.close()
