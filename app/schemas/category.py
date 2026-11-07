from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    display_order: int = Field(default=0)
    keywords: list[str] = Field(default_factory=list)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    display_order: int | None = None
    keywords: list[str] | None = None
    touch_updated_at: bool = Field(
        default=False,
        description="Se True, marca a seção como atualizada agora (fonte WEB)",
    )


class CategoryHealthResponse(BaseModel):
    """Status de atualização de uma seção para o monitoramento de 24h no topo do Dashboard."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    display_order: int
    last_updated_at: datetime | None = None
    last_update_source: str | None = None
    hours_since_update: float | None = Field(
        default=None,
        description="Horas decorridas desde a última atualização (None se nunca atualizado)",
    )
    human_time_since_update: str = Field(
        default="Nunca atualizado",
        description="Texto amigável como 'Há 2 horas' ou 'Há 30 minutos'",
    )
    is_stale: bool = Field(
        default=True,
        description="True se last_updated_at for nulo ou > STALE_SECTION_HOURS (24h)",
    )
    stale_alert_message: str | None = Field(
        default=None,
        description="Mensagem de alerta caso a seção esteja atrasada (> 24h)",
    )
    total_products: int = 0
    critical_count: int = 0
    warning_count: int = 0
    portioned_count: int = 0
    incomplete_count: int = 0
    alert_items_count: int = Field(
        default=0,
        description="Soma de itens CRITICAL + WARNING na seção",
    )


class CategoryResponse(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    last_updated_at: datetime | None = None
    last_update_source: str | None = None
