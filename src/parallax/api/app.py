from __future__ import annotations
from fastapi import FastAPI
from parallax.api.routes import audit, candidates, markets

app = FastAPI(title="PARALLAX", version="0.1.0")

app.include_router(candidates.router, prefix="/api")
app.include_router(markets.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
