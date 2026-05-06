import time
from contextlib import asynccontextmanager
from typing import Dict, Tuple
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from parallax.api.routes import audit, candidates, markets, ops, positions, telemetry
from parallax.config import settings
from parallax.db.session import SessionLocal, engine
from parallax.ops.runtime import build_readiness_payload
from parallax.ops.schemas import ReadinessReport
import anyio

from parallax.ops.telemetry import setup_async_logging

settings.validate_runtime_safety()
setup_async_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Loop-agnostic background task management using AnyIO.
    """
    async with anyio.create_task_group() as tg:
        # Launch Semantic Agent background loop (Cold Path NLP scanner)
        from parallax.graph.semantic_scheduler import run_semantic_scan_loop
        tg.start_soon(run_semantic_scan_loop, SessionLocal)

        yield  # App is running

        # Task Group will automatically cancel tasks on exit
        # Close Neo4j driver
        from parallax.graph.neo4j_driver import close_driver
        close_driver()


app = FastAPI(
    title="PARALLAX",
    version="0.2.0",
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    lifespan=lifespan,
)

# ── Security & Infrastructure Middlewares ──────────────────────────────────
# BUG-050 Fix: TrustedHost must come before CORS for efficiency
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

# BUG-046: Simple In-Memory Rate Limiter
_rate_limit_store: Dict[str, Tuple[int, float]] = {}

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    # Very basic: 100 requests per 60 seconds
    limit = 100
    window = 60
    
    count, start_time = _rate_limit_store.get(client_ip, (0, now))
    
    if now - start_time > window:
        count = 1
        start_time = now
    else:
        count += 1
        
    _rate_limit_store[client_ip] = (count, start_time)
    
    if count > limit:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})
        
    return await call_next(request)

# BUG-049: Request ID Tracking
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    import uuid
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(candidates.router, prefix="/api")
app.include_router(markets.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(ops.router, prefix="/api")
app.include_router(positions.router, prefix="/api")
app.include_router(telemetry.router, prefix="/api")


@app.get("/health")
def health(request: Request):
    # BUG-048: Protect sensitive config info from unauthenticated users
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {settings.api_auth_token}":
        return {"status": "ok"}
        
    return {
        "status": "ok",
        "docs_enabled": settings.api_docs_enabled,
        "write_auth_enabled": settings.api_require_auth_for_writes,
        "read_auth_enabled": bool(settings.api_auth_token and settings.api_require_auth_for_reads),
    }


@app.get("/ready", response_model=ReadinessReport)
async def ready(request: Request) -> ReadinessReport:
    # BUG-046: Require auth for heavy readiness probe in production
    if settings.app_env.lower() != "dev":
        token = request.headers.get("X-API-Token")
        if not token or token != settings.api_auth_token:
            raise HTTPException(status_code=401, detail="Unauthorized readiness probe")

    # BUG-047: Should be async (placeholder for now, wrapping in to_thread)
    def check_db():
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        with SessionLocal() as session:
            return build_readiness_payload(session)
            
    return await anyio.to_thread.run_sync(check_db)

