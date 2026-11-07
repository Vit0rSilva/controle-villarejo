from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import StockServiceDep
from app.core.exceptions import EntityNotFoundError
from app.models.product import StockStatus
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate

router = APIRouter()


@router.get(
    "",
    response_model=list[ProductResponse],
    summary="Lista produtos filtrados por seção, status de falta ou busca textual",
)
async def list_products(
    stock_service: StockServiceDep,
    category_id: UUID | None = Query(default=None),
    status_filter: StockStatus | None = Query(default=None, alias="status"),
    needs_restock: bool | None = Query(default=None),
    is_incomplete_data: bool | None = Query(default=None),
    search: str | None = Query(default=None),
) -> list[ProductResponse]:
    products = await stock_service.product_repo.list_all(
        category_id=category_id,
        status=status_filter,
        needs_restock=needs_restock,
        is_incomplete_data=is_incomplete_data,
        search=search,
    )
    return [stock_service.to_product_response(p) for p in products]


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um novo produto manualmente pelo painel web",
)
async def create_product(
    payload: ProductCreate,
    stock_service: StockServiceDep,
) -> ProductResponse:
    return await stock_service.create_product_manual(payload)


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Edição rápida de produto via painel web com recálculo automático de stock_status",
)
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    stock_service: StockServiceDep,
) -> ProductResponse:
    return await stock_service.update_product_manual(product_id, payload)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um produto do estoque",
)
async def delete_product(
    product_id: UUID,
    stock_service: StockServiceDep,
) -> None:
    product = await stock_service.product_repo.get_by_id(product_id)
    if product is None:
        raise EntityNotFoundError("Produto", product_id)
    await stock_service.product_repo.delete(product)
    await stock_service.session.commit()
