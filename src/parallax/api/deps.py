from __future__ import annotations
from typing import Generator
from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session
from parallax.config import settings
from parallax.db.session import SessionLocal


def get_read_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_write_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_read_access(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> None:
    if not settings.api_auth_token or not settings.api_require_auth_for_reads:
        return
    _validate_token(authorization=authorization, x_api_token=x_api_token)


def require_write_access(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> None:
    if not settings.api_auth_token:
        return
    _validate_token(authorization=authorization, x_api_token=x_api_token)


def _validate_token(authorization: str | None, x_api_token: str | None) -> None:
    token = _extract_token(authorization=authorization, x_api_token=x_api_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token != settings.api_auth_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API token",
        )


def _extract_token(authorization: str | None, x_api_token: str | None) -> str | None:
    if x_api_token and x_api_token.strip():
        return x_api_token.strip()
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
