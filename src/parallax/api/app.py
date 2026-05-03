from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from parallax.api.routes import audit, candidates, markets, ops, positions
from parallax.config import settings
from parallax.db.session import SessionLocal, engine
from parallax.ops.runtime import build_readiness_payload
from parallax.ops.schemas import ReadinessReport

settings.validate_runtime_safety()

app = FastAPI(
    title="PARALLAX",
    version="0.1.0",
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

if settings.trusted_hosts_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)

if settings.cors_allowed_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-Token"],
    )

app.include_router(candidates.router, prefix="/api")
app.include_router(markets.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(ops.router, prefix="/api")
app.include_router(positions.router, prefix="/api")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "docs_enabled": settings.api_docs_enabled,
        "write_auth_enabled": bool(settings.api_auth_token),
        "read_auth_enabled": bool(settings.api_auth_token and settings.api_require_auth_for_reads),
    }


@app.get("/ready", response_model=ReadinessReport)
def ready() -> ReadinessReport:
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    with SessionLocal() as session:
        return build_readiness_payload(session)
