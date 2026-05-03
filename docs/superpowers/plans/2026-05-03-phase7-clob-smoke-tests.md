# Fase 7 — CLOB Adapter Smoke Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the CLOB adapters parse real network responses correctly; add optional Kalshi API key support so real Kalshi orderbook data can flow when credentials are available.

**Architecture:** Two independent streams. First, add `kalshi_api_key` to `Settings` and thread it through `KalshiQuoteAdapter` as an optional `Authorization` header — this unlocks real Kalshi data without breaking anything when the key is absent. Second, add a `tests/smoke/` directory that skips cleanly when `SMOKE_CLOB=1` is not set; the smoke tests hit real endpoints and verify response shapes, accepting `None` gracefully when auth is absent.

**Tech Stack:** Python 3.13, httpx (async), pytest with autouse skip guard, Polymarket Gamma REST API (public), Kalshi elections REST API (auth optional).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/parallax/config.py` | Add `kalshi_api_key: str = ""` |
| Modify | `src/parallax/execution/kalshi_quote_adapter.py` | Accept `api_key` param; add `Authorization` header when non-empty |
| Modify | `src/parallax/execution/fetcher.py` | Pass `settings.kalshi_api_key` to `KalshiQuoteAdapter` |
| Modify | `tests/unit/test_kalshi_quote_adapter.py` | Tests for auth header present/absent |
| Modify | `tests/unit/test_execution_fetcher.py` | Test that `kalshi_api_key` is forwarded |
| Create | `tests/smoke/__init__.py` | Empty — makes directory a package |
| Create | `tests/smoke/conftest.py` | Autouse skip guard when `SMOKE_CLOB != "1"` |
| Create | `tests/smoke/test_clob_smoke.py` | Live Polymarket + Kalshi smoke tests |
| Modify | `docs/STATUS.md` | Document Fase 7 |

---

### Task 1: Kalshi auth support

**Files:**
- Modify: `src/parallax/config.py`
- Modify: `src/parallax/execution/kalshi_quote_adapter.py`
- Modify: `src/parallax/execution/fetcher.py`
- Test: `tests/unit/test_kalshi_quote_adapter.py`
- Test: `tests/unit/test_execution_fetcher.py`

- [ ] **Step 1: Write failing unit tests for auth header**

Add to `tests/unit/test_kalshi_quote_adapter.py` (after existing tests):

```python
@pytest.mark.anyio
async def test_fetch_snapshot_sends_auth_header_when_key_set():
    body = {
        "orderbook": {
            "yes": [[55, 100]],
            "no": [[46, 80]],
        }
    }
    client = _mock_client(200, body)
    adapter = KalshiQuoteAdapter(http_client=client, api_key="test-key-abc")
    await adapter.fetch_snapshot("KXTEST-24", "YES")

    call_kwargs = client.get.call_args[1]
    assert "headers" in call_kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key-abc"


@pytest.mark.anyio
async def test_fetch_snapshot_no_auth_header_when_key_empty():
    body = {
        "orderbook": {
            "yes": [[55, 100]],
            "no": [],
        }
    }
    client = _mock_client(200, body)
    adapter = KalshiQuoteAdapter(http_client=client, api_key="")
    await adapter.fetch_snapshot("KXTEST-24", "YES")

    call_kwargs = client.get.call_args[1]
    headers = call_kwargs.get("headers", {})
    assert "Authorization" not in headers
```

Add to `tests/unit/test_execution_fetcher.py` (after existing tests):

```python
@pytest.mark.anyio
async def test_fetcher_passes_kalshi_api_key_to_adapter():
    """OrderbookFetcher constructs KalshiQuoteAdapter with the api_key from settings."""
    from unittest.mock import patch, MagicMock

    snap = _fresh_snap("kalshi")
    kalshi_mock = AsyncMock()
    kalshi_mock.fetch_snapshot = AsyncMock(return_value=snap)

    settings_with_key = Settings(orderbook_enabled=True, kalshi_api_key="live-key-xyz")

    with patch(
        "parallax.execution.fetcher.KalshiQuoteAdapter", return_value=kalshi_mock
    ) as MockKalshi:
        fetcher = OrderbookFetcher(settings_with_key)
        await fetcher.fetch("kalshi", "KXTEST-24", "YES")

    init_kwargs = MockKalshi.call_args[1]
    assert init_kwargs.get("api_key") == "live-key-xyz"
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /home/administrator/tools/parallax
.venv/bin/python -m pytest tests/unit/test_kalshi_quote_adapter.py::test_fetch_snapshot_sends_auth_header_when_key_set tests/unit/test_kalshi_quote_adapter.py::test_fetch_snapshot_no_auth_header_when_key_empty tests/unit/test_execution_fetcher.py::test_fetcher_passes_kalshi_api_key_to_adapter -v
```

Expected: `TypeError` or `AssertionError` — `api_key` param doesn't exist yet.

- [ ] **Step 3: Add `kalshi_api_key` to `Settings`**

In `src/parallax/config.py`, add after `orderbook_partial_fill_inversion_threshold`:

```python
    # Orderbook reality layer
    orderbook_enabled: bool = False
    orderbook_snapshot_ttl_seconds: float = 45.0
    orderbook_fetch_timeout_seconds: float = 5.0
    court_max_quote_staleness_seconds: float = 60.0
    court_min_depth_size: float = 10.0
    court_partial_fill_inversion_threshold: float = 0.4
    kalshi_api_key: str = ""
```

- [ ] **Step 4: Add `api_key` param to `KalshiQuoteAdapter`**

Replace `src/parallax/execution/kalshi_quote_adapter.py` `__init__` and `_fetch`:

```python
class KalshiQuoteAdapter:
    """Read-only orderbook fetcher for Kalshi markets."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
        api_key: str = "",
    ) -> None:
        self._client = http_client
        self._timeout = timeout
        self._api_key = api_key

    async def fetch_snapshot(
        self, market_id: str, outcome: str
    ) -> OrderbookSnapshot | None:
        """Fetch live orderbook for a Kalshi market ticker. Returns None on any error."""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        own = self._client is None
        try:
            return await self._fetch(client, market_id, outcome)
        except Exception:
            return None
        finally:
            if own:
                await client.aclose()

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        market_id: str,
        outcome: str,
    ) -> OrderbookSnapshot | None:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        resp = await client.get(
            f"{_KALSHI_BASE}/markets/{market_id}/orderbook",
            timeout=self._timeout,
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("orderbook", {})
        yes_bids, yes_asks = _parse_kalshi_sides(data, outcome)
        mid = _mid_price(yes_bids, yes_asks)
        spread = _spread_bps(yes_bids, yes_asks)
        return OrderbookSnapshot(
            id=str(uuid.uuid4()),
            platform="kalshi",
            market_id=market_id,
            token_id=None,
            outcome=outcome,
            captured_at=datetime.now(timezone.utc),
            bids=yes_bids,
            asks=yes_asks,
            mid_price=mid,
            spread_bps=spread,
        )
```

- [ ] **Step 5: Update `OrderbookFetcher` to forward `kalshi_api_key`**

In `src/parallax/execution/fetcher.py`, update `__init__`:

```python
class OrderbookFetcher:
    """
    Unified entry point: given (platform, market_id, outcome, token_id),
    dispatch to the correct adapter and return a snapshot or None.
    """

    def __init__(
        self,
        settings: Settings,
        polymarket_adapter: PolymarketCLOBAdapter | None = None,
        kalshi_adapter: KalshiQuoteAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._poly = polymarket_adapter or PolymarketCLOBAdapter(
            timeout=settings.orderbook_fetch_timeout_seconds
        )
        self._kalshi = kalshi_adapter or KalshiQuoteAdapter(
            timeout=settings.orderbook_fetch_timeout_seconds,
            api_key=settings.kalshi_api_key,
        )

    async def fetch(
        self,
        platform: str,
        market_id: str,
        outcome: str,
        token_id: str | None = None,
    ) -> OrderbookSnapshot | None:
        if not self._settings.orderbook_enabled:
            return None
        if platform == "polymarket":
            if not token_id:
                return None
            return await self._poly.fetch_snapshot(market_id, outcome, token_id)
        if platform == "kalshi":
            return await self._kalshi.fetch_snapshot(market_id, outcome)
        return None
```

- [ ] **Step 6: Run the three new tests**

```bash
.venv/bin/python -m pytest tests/unit/test_kalshi_quote_adapter.py::test_fetch_snapshot_sends_auth_header_when_key_set tests/unit/test_kalshi_quote_adapter.py::test_fetch_snapshot_no_auth_header_when_key_empty tests/unit/test_execution_fetcher.py::test_fetcher_passes_kalshi_api_key_to_adapter -v
```

Expected: all 3 PASS.

- [ ] **Step 7: Full unit suite — no regressions**

```bash
.venv/bin/python -m pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: `N passed`.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/parallax/config.py src/parallax/execution/kalshi_quote_adapter.py src/parallax/execution/fetcher.py tests/unit/test_kalshi_quote_adapter.py tests/unit/test_execution_fetcher.py
git commit -m "feat(fase-7): Kalshi API key support — optional Authorization header in KalshiQuoteAdapter"
```

---

### Task 2: Smoke test infrastructure

**Files:**
- Create: `tests/smoke/__init__.py`
- Create: `tests/smoke/conftest.py`

- [ ] **Step 1: Create `tests/smoke/__init__.py`**

```python
```
(empty file)

- [ ] **Step 2: Create `tests/smoke/conftest.py`**

```python
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
```

- [ ] **Step 3: Verify skip works**

```bash
.venv/bin/python -m pytest tests/smoke/ -v 2>&1 | head -10
```

Expected: `SKIPPED` with message `CLOB smoke tests disabled. Set SMOKE_CLOB=1 to run.`

(No files yet in tests/smoke other than conftest, so this will just show 0 items collected or the skip message.)

- [ ] **Step 4: Confirm full test suite still passes with smoke dir present**

```bash
.venv/bin/python -m pytest tests/unit/ -q 2>&1 | tail -3
```

Expected: `N passed`.

- [ ] **Step 5: Commit Task 2**

```bash
git add tests/smoke/__init__.py tests/smoke/conftest.py
git commit -m "feat(fase-7): smoke test infrastructure — SMOKE_CLOB=1 skip guard"
```

---

### Task 3: Smoke tests for Polymarket and Kalshi adapters

**Files:**
- Create: `tests/smoke/test_clob_smoke.py`

Context for the tests:
- Polymarket CLOB is public. Gamma API (`https://gamma-api.polymarket.com`) is used to dynamically find a live market with a token ID.
- Kalshi elections API (`https://api.elections.kalshi.com/trade-api/v2`) may require auth. The test accepts `None` gracefully.
- Both tests verify response _shape_ when a snapshot is returned: `mid_price` in `(0.0, 1.0)`, bids/asks are lists.
- These tests make real network calls — they are slow by design and only run when `SMOKE_CLOB=1`.

- [ ] **Step 1: Create `tests/smoke/test_clob_smoke.py`**

```python
from __future__ import annotations

import httpx
import pytest

from parallax.execution.clob_adapter import PolymarketCLOBAdapter
from parallax.execution.kalshi_quote_adapter import KalshiQuoteAdapter
from parallax.execution.schemas import OrderbookSnapshot


def _assert_snapshot_shape(snap: OrderbookSnapshot) -> None:
    """Assert a live snapshot has a valid shape."""
    assert snap.platform in {"polymarket", "kalshi"}
    assert isinstance(snap.bids.levels, list)
    assert isinstance(snap.asks.levels, list)
    if snap.mid_price is not None:
        assert 0.0 < snap.mid_price < 1.0, f"mid_price={snap.mid_price} out of (0,1)"
    if snap.spread_bps is not None:
        assert snap.spread_bps >= 0.0


@pytest.mark.anyio
async def test_polymarket_clob_fetch_live():
    """
    Dynamically resolve a live Polymarket market via Gamma API, then fetch its CLOB book.
    Verifies: snapshot is not None, shape is valid, mid_price is in (0, 1).
    """
    gamma_url = "https://gamma-api.polymarket.com/markets"
    params = {"active": "true", "closed": "false", "limit": 1}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(gamma_url, params=params)

    assert resp.status_code == 200, f"Gamma API returned {resp.status_code}"
    markets = resp.json()
    assert isinstance(markets, list) and len(markets) > 0, "No active markets returned"

    market = markets[0]
    clob_token_ids = market.get("clobTokenIds") or []
    outcomes = market.get("outcomes") or []

    assert len(clob_token_ids) > 0, f"No clobTokenIds in market: {market.get('id')}"
    assert len(outcomes) > 0, f"No outcomes in market: {market.get('id')}"

    token_id = clob_token_ids[0]
    outcome = outcomes[0]
    market_id = market.get("id") or market.get("conditionId") or "unknown"

    adapter = PolymarketCLOBAdapter(timeout=8.0)
    snap = await adapter.fetch_snapshot(market_id=str(market_id), outcome=str(outcome), token_id=str(token_id))

    assert snap is not None, (
        f"fetch_snapshot returned None for token_id={token_id!r}. "
        "Check CLOB API reachability or token ID format."
    )
    _assert_snapshot_shape(snap)
    assert snap.platform == "polymarket"
    assert snap.token_id == str(token_id)


@pytest.mark.anyio
async def test_kalshi_orderbook_fetch_live():
    """
    Attempt to fetch a known Kalshi market orderbook.
    Without API key, the adapter returns None gracefully (expected on auth-required endpoints).
    With KALSHI_API_KEY set, verifies full snapshot shape.
    """
    import os

    # Use any known Kalshi ticker; update to a current one if needed.
    # Kalshi tickers have format like KXBTCD-25DEC31-B60000 or KXFED-25MAY07-B5.25.
    # The exact value matters less than proving the graceful-None path works.
    ticker = os.environ.get("SMOKE_KALSHI_TICKER", "KXFED-25MAY07-B5.25")
    api_key = os.environ.get("KALSHI_API_KEY", "")

    adapter = KalshiQuoteAdapter(timeout=8.0, api_key=api_key)
    snap = await adapter.fetch_snapshot(market_id=ticker, outcome="YES")

    if api_key:
        # With credentials, expect a real snapshot
        assert snap is not None, (
            f"fetch_snapshot returned None for ticker={ticker!r} even with KALSHI_API_KEY set. "
            "Check ticker validity or API key scope."
        )
        _assert_snapshot_shape(snap)
        assert snap.platform == "kalshi"
    else:
        # Without credentials: graceful None is the correct behavior (401 → None)
        # The adapter must not raise; returning None is acceptable.
        assert snap is None or isinstance(snap, OrderbookSnapshot), (
            "fetch_snapshot must return None or OrderbookSnapshot, never raise"
        )
        # If the Kalshi elections endpoint happens to be public, a snapshot is also fine
        if snap is not None:
            _assert_snapshot_shape(snap)
```

- [ ] **Step 2: Verify smoke tests skip when `SMOKE_CLOB` is not set**

```bash
.venv/bin/python -m pytest tests/smoke/ -v 2>&1
```

Expected: `SKIPPED` — `CLOB smoke tests disabled.`

- [ ] **Step 3: Run smoke tests live (requires network)**

```bash
SMOKE_CLOB=1 .venv/bin/python -m pytest tests/smoke/ -v -s 2>&1
```

Expected: both tests PASS. If Polymarket CLOB is down or returns unexpected JSON, the test will fail with a descriptive assertion message. Fix the Gamma API query or token parsing if so.

If `test_kalshi_orderbook_fetch_live` fails even without api_key (i.e., the adapter raises instead of returning None), trace the exception through `KalshiQuoteAdapter._fetch` — the outer `try/except Exception: return None` should absorb it.

- [ ] **Step 4: Run full unit suite to confirm no regressions**

```bash
.venv/bin/python -m pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: `N passed`.

- [ ] **Step 5: Commit Task 3**

```bash
git add tests/smoke/test_clob_smoke.py
git commit -m "feat(fase-7): live CLOB smoke tests for Polymarket and Kalshi adapters"
```

---

### Task 4: Update `docs/STATUS.md`

**Files:**
- Modify: `docs/STATUS.md`

- [ ] **Step 1: Add Fase 7 section**

In `docs/STATUS.md`, add the following after the `## Automated Settlement Layer (Fase 6 — 2026-05-03)` section and before `## Verified But Still Heuristic`:

```markdown
## CLOB Adapter Smoke Tests (Fase 7 — 2026-05-03)

The CLOB adapters are now verified against real network endpoints:

- `KalshiQuoteAdapter` gains optional `api_key: str = ""` constructor param; passes `Authorization: Bearer {key}` header when non-empty
- `Settings.kalshi_api_key: str = ""` — set via `KALSHI_API_KEY` env var; forwarded by `OrderbookFetcher` at construction time
- `tests/smoke/` — new smoke test directory with `SMOKE_CLOB=1` skip guard (same pattern as integration tests)
- `tests/smoke/test_clob_smoke.py` — two live tests:
  - `test_polymarket_clob_fetch_live`: resolves a live market from Gamma API, fetches CLOB book, asserts snapshot shape
  - `test_kalshi_orderbook_fetch_live`: attempts Kalshi orderbook fetch; accepts `None` gracefully when no API key set; verifies full shape when `KALSHI_API_KEY` is present
- Run with: `SMOKE_CLOB=1 pytest tests/smoke/ -v`
- Run with Kalshi key: `SMOKE_CLOB=1 KALSHI_API_KEY=<key> SMOKE_KALSHI_TICKER=<ticker> pytest tests/smoke/ -v`
```

Also update the heuristic caveat bullet:

Change:
```
- orderbook snapshot path is not yet tested against live CLOB APIs; adapters are implemented and unit-tested with mocks
```
To:
```
- orderbook snapshot path is smoke-tested against live CLOB APIs (`SMOKE_CLOB=1`); Polymarket CLOB confirmed reachable; Kalshi requires `KALSHI_API_KEY` for live data
```

- [ ] **Step 2: Commit Task 4**

```bash
git add docs/STATUS.md
git commit -m "docs: document Fase 7 CLOB smoke tests and Kalshi auth support in STATUS.md"
```

---

## Self-Review

**1. Spec coverage:**
- Kalshi auth support → Task 1 ✓
- `kalshi_api_key` in `Settings` → Task 1 ✓
- `KalshiQuoteAdapter` api_key param + auth header → Task 1 ✓
- `OrderbookFetcher` forwarding → Task 1 ✓
- Smoke test skip guard → Task 2 ✓
- Polymarket live fetch smoke test → Task 3 ✓
- Kalshi live fetch smoke test (graceful None + keyed path) → Task 3 ✓
- STATUS.md → Task 4 ✓

**2. Placeholder scan:** None — all steps have complete code.

**3. Type consistency:**
- `KalshiQuoteAdapter.__init__(http_client, timeout, api_key)` — consistent across Task 1 implementation and Task 3 smoke test instantiation (`KalshiQuoteAdapter(timeout=8.0, api_key=api_key)`)
- `OrderbookFetcher.__init__` uses `settings.kalshi_api_key` — field added to `Settings` in Task 1 Step 3
- `_assert_snapshot_shape(snap: OrderbookSnapshot)` — defined and used only in `test_clob_smoke.py`
- `fetch_snapshot(market_id, outcome, token_id)` for Polymarket / `fetch_snapshot(market_id, outcome)` for Kalshi — unchanged signatures, consistent with existing unit tests
