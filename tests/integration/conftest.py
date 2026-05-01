from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from parallax.db.models import Base

TEST_DATABASE_URL = "postgresql://parallax:dev_password@localhost:5433/parallax_test"


def _db_reachable() -> bool:
    try:
        engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


_DB_AVAILABLE = _db_reachable()


@pytest.fixture(scope="session", autouse=True)
def require_db():
    if not _DB_AVAILABLE:
        pytest.skip("postgres_test not reachable on port 5433", allow_module_level=True)


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
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
