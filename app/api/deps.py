from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import verify_webhook_token
from app.services.evolution_service import EvolutionService
from app.services.stock_service import StockService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


DBSessionDep = Annotated[AsyncSession, Depends(get_db)]
WebhookAuthDep = Annotated[bool, Depends(verify_webhook_token)]


def get_stock_service(db: DBSessionDep) -> StockService:
    return StockService(db)


def get_evolution_service() -> EvolutionService:
    return EvolutionService()


StockServiceDep = Annotated[StockService, Depends(get_stock_service)]
EvolutionServiceDep = Annotated[EvolutionService, Depends(get_evolution_service)]
