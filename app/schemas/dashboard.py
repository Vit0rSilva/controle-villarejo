from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.category import CategoryHealthResponse
from app.schemas.product import ProductResponse


class MissingProductSummaryItem(BaseModel):
    """Item resumido na lista rápida de compras / reposição (CRITICAL e WARNING)."""

    id: UUID
    canonical_name: str
    category_id: UUID
    category_name: str
    raw_main_value: str
    sub_attributes: dict
    stock_status: str
    status_note: str | None = None
    is_incomplete_data: bool = False
    updated_at: datetime


class DashboardSectionWithProducts(BaseModel):
    """Seção completa com seus metadados de saúde e lista de produtos ordenados."""

    health: CategoryHealthResponse
    products: list[ProductResponse] = Field(default_factory=list)


class DashboardStats(BaseModel):
    total_sections: int = 0
    stale_sections_count: int = 0
    total_products: int = 0
    critical_products_count: int = 0
    warning_products_count: int = 0
    portioned_products_count: int = 0
    ok_products_count: int = 0
    incomplete_products_count: int = 0


class DashboardResponse(BaseModel):
    """Payload consolidado retornado por GET /api/v1/dashboard."""

    generated_at: datetime
    stale_threshold_hours: int
    stats: DashboardStats
    sections_health: list[CategoryHealthResponse]
    missing_products_summary: list[MissingProductSummaryItem]
    sections: list[DashboardSectionWithProducts]
