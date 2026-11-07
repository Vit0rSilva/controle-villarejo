from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import StockServiceDep
from app.core.exceptions import EntityNotFoundError
from app.schemas.category import (
    CategoryCreate,
    CategoryHealthResponse,
    CategoryUpdate,
)
from app.services.fuzzy_service import FuzzyService

router = APIRouter()


@router.get(
    "",
    response_model=list[CategoryHealthResponse],
    summary="Lista todas as seções do estoque com status de atraso (> 24h) e contadores",
)
async def list_sections(
    stock_service: StockServiceDep,
) -> list[CategoryHealthResponse]:
    await stock_service.category_repo.ensure_default_categories()
    categories = await stock_service.category_repo.list_all_ordered(include_products=True)
    now = datetime.now(timezone.utc)
    return [stock_service.compute_category_health(cat, now=now) for cat in categories]


@router.post(
    "",
    response_model=CategoryHealthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria uma nova seção de estoque",
)
async def create_section(
    payload: CategoryCreate,
    stock_service: StockServiceDep,
) -> CategoryHealthResponse:
    slug = payload.slug or FuzzyService.slugify(payload.name)
    category = await stock_service.category_repo.create(
        name=payload.name,
        slug=slug,
        display_order=payload.display_order,
        keywords=payload.keywords,
    )
    await stock_service.session.commit()
    category.products = []
    return stock_service.compute_category_health(category)


@router.patch(
    "/{section_id}",
    response_model=CategoryHealthResponse,
    summary="Atualiza metadados ou confirma atualização manual (timestamp) de uma seção",
)
async def update_section(
    section_id: UUID,
    payload: CategoryUpdate,
    stock_service: StockServiceDep,
) -> CategoryHealthResponse:
    category = await stock_service.category_repo.get_by_id(section_id, include_products=True)
    if category is None:
        raise EntityNotFoundError("Seção", section_id)

    if payload.name is not None:
        category.name = payload.name.strip()
        category.slug = FuzzyService.slugify(payload.name)
    if payload.display_order is not None:
        category.display_order = payload.display_order
    if payload.keywords is not None:
        category.keywords = payload.keywords
    if payload.touch_updated_at:
        await stock_service.category_repo.touch_timestamp(category, source="WEB")

    await stock_service.category_repo.save(category)
    await stock_service.session.commit()
    return stock_service.compute_category_health(category)
