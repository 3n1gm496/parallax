from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from parallax.api.deps import get_session
from parallax.ingestion.market_repository import MarketRepository
from parallax.shared.schemas import MarketDetail, MarketSummary

router = APIRouter(tags=["markets"])


@router.get("/markets", response_model=list[MarketSummary])
def list_markets(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[MarketSummary]:
    repo = MarketRepository(session)
    rows = repo.list_open(limit=limit, offset=offset)
    return [
        MarketSummary(
            id=r.id,
            platform=r.platform,
            title=r.title,
            outcome_prices=r.outcome_prices,
            group_id=r.group_id,
            deadline=r.deadline,
            is_closed=r.is_closed,
        )
        for r in rows
    ]


@router.get("/markets/{market_id:path}", response_model=MarketDetail)
def get_market(
    market_id: str,
    session: Session = Depends(get_session),
) -> MarketDetail:
    repo = MarketRepository(session)
    row = repo.get(market_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Market not found")

    from parallax.db.models import CompiledContract
    contract_row = (
        session.query(CompiledContract)
        .filter_by(raw_market_id=row.id)
        .order_by(CompiledContract.compiled_at.desc())
        .first()
    )
    from parallax.shared.schemas import ContractSchema
    contract = ContractSchema.model_validate(contract_row.contract_json) if contract_row else None

    return MarketDetail(
        id=row.id,
        platform=row.platform,
        title=row.title,
        description=row.description,
        resolution_criteria=row.resolution_criteria,
        outcome_prices=row.outcome_prices,
        group_id=row.group_id,
        deadline=row.deadline,
        is_closed=row.is_closed,
        resolution_source=row.resolution_source,
        contract=contract,
    )
