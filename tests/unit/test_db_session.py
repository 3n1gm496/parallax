from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError


def test_session_scope_retries_after_operational_error(monkeypatch):
    from parallax.db import session as db_session

    first = MagicMock()
    first.connection.side_effect = OperationalError("", {}, None)
    second = MagicMock()
    second.connection.return_value = MagicMock()
    factory_a = MagicMock(return_value=first)
    factory_b = MagicMock(return_value=second)
    rebuilt_engine = MagicMock()
    dispose = MagicMock()

    monkeypatch.setattr(db_session, "SessionLocal", factory_a)
    monkeypatch.setattr(db_session.engine, "dispose", dispose)
    monkeypatch.setattr(db_session, "_build_engine", MagicMock(return_value=rebuilt_engine))
    monkeypatch.setattr(
        db_session,
        "sessionmaker",
        MagicMock(return_value=factory_b),
    )

    with db_session.session_scope() as session:
        assert session is second

    dispose.assert_called_once()
    first.close.assert_called_once()
    second.close.assert_called_once()
