from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.product import StockStatus


class ProductBase(BaseModel):
    canonical_name: str = Field(..., min_length=1, max_length=180)
    raw_main_value: str = Field(default="", max_length=255)
    numeric_quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=64)
    sub_attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    is_incomplete_data: bool = False


class ProductCreate(ProductBase):
    category_id: UUID


class ProductUpdate(BaseModel):
    """Payload para edição rápida (inline ou modal) de um produto no painel web."""

    canonical_name: str | None = Field(default=None, min_length=1, max_length=180)
    category_id: UUID | None = None
    raw_main_value: str | None = Field(default=None, max_length=255)
    numeric_quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=64)
    sub_attributes: dict[str, Any] | None = None
    aliases: list[str] | None = None
    is_incomplete_data: bool | None = None
    stock_status_override: StockStatus | None = Field(
        default=None,
        description="Permite forçar um status manualmente se desejado; caso None, recalcula automaticamente",
    )
    update_section_timestamp: bool = Field(
        default=True,
        description="Se True, atualiza também o last_updated_at da seção para agora (fonte WEB)",
    )


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    category_name: str | None = None
    canonical_name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    raw_main_value: str
    numeric_quantity: float | None = None
    unit: str | None = None
    sub_attributes: dict[str, Any] = Field(default_factory=dict)
    stock_status: StockStatus
    needs_restock: bool
    is_incomplete_data: bool
    status_note: str | None = Field(
        default=None,
        description="Explicação amigável do status (ex: 'Bruto zerado (Restam 35 porções de 100g)')",
    )
    updated_at: datetime
