# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/graph/neo4j_driver.py
#
# Singleton Neo4j driver for Parallax.
# Manages the connection lifecycle to avoid re-creating the driver on every
# request. The driver is initialized lazily on first use.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_driver = None


def get_driver():
    """
    Returns a singleton Neo4j AsyncDriver, creating it on first call.
    Reads credentials from parallax.config.settings.
    """
    global _driver
    if _driver is not None:
        return _driver

    from parallax.config import settings
    try:
        from neo4j import AsyncGraphDatabase  # type: ignore[import]
    except ImportError:
        logger.warning("neo4j package not installed — graph features disabled.")
        return None

    uri = getattr(settings, "neo4j_uri", "bolt://localhost:7687")
    user = getattr(settings, "neo4j_user", "neo4j")
    password = getattr(settings, "neo4j_password", "parallax")

    if not uri or uri == "disabled":
        logger.info("Neo4j URI not configured — graph layer running in offline mode.")
        return None

    try:
        _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"✅  Neo4j async driver initialized → {uri}")
    except Exception as exc:
        logger.warning(f"⚠️  Neo4j not reachable ({exc}). Graph layer in offline mode.")
        _driver = None

    return _driver


async def close_driver():
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
