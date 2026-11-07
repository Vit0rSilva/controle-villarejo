from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_log import StockLog


class LogRepository:
    """Camada de acesso a dados para auditoria de mensagens brutas recebidas."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        instance_name: str,
        raw_message: str,
        parsed_items_count: int,
        unrecognized_lines: list[str] | None = None,
        sender_phone: str | None = None,
    ) -> StockLog:
        log = StockLog(
            instance_name=instance_name,
            sender_phone=sender_phone,
            raw_message=raw_message,
            parsed_items_count=parsed_items_count,
            unrecognized_lines=unrecognized_lines or [],
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def list_recent(self, limit: int = 25) -> list[StockLog]:
        stmt = select(StockLog).order_by(StockLog.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
