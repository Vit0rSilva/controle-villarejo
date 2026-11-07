from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.category import Category


class StockStatus(str, enum.Enum):
    """Status calculado do estoque do produto."""

    OK = "OK"
    PORTIONED = "PORTIONED"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    NEEDS_ACTION = "NEEDS_ACTION"


class Product(Base):
    """Modelo ORM representando um produto monitorado no estoque."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    canonical_name: Mapped[str] = mapped_column(
        String(180),
        index=True,
        nullable=False,
    )
    normalized_name: Mapped[str] = mapped_column(
        String(180),
        index=True,
        nullable=False,
    )
    aliases: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        default=list,
        nullable=False,
    )
    raw_main_value: Mapped[str] = mapped_column(
        String(255),
        default="",
        nullable=False,
    )
    numeric_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3),
        nullable=True,
    )
    unit: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    sub_attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        default=dict,
        nullable=False,
    )
    stock_status: Mapped[StockStatus] = mapped_column(
        SAEnum(StockStatus, name="stock_status_enum"),
        default=StockStatus.OK,
        nullable=False,
    )
    needs_restock: Mapped[bool] = mapped_column(
        Boolean,
        index=True,
        default=False,
        nullable=False,
    )
    is_incomplete_data: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    category: Mapped[Category] = relationship(
        "Category",
        back_populates="products",
    )
