from __future__ import annotations
import os
import pytest


def _smoke_enabled() -> bool:
    return os.environ.get("SMOKE_CLOB", "0").strip() == "1"


@pytest.fixture(scope="session", autouse=True)
def require_smoke_enabled():
    if not _smoke_enabled():
        pytest.skip(
            "CLOB smoke tests disabled. Set SMOKE_CLOB=1 to run.",
            allow_module_level=True,
        )
