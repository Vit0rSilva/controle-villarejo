from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, JSON, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StockLog(Base):
    """Histórico de mensagens brutas recebidas e auditoria de processamento."""

    __tablename__ = "stock_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    instance_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    sender_phone: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    raw_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    parsed_items_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    unrecognized_lines: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        default=list,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
