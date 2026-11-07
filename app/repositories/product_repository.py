from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.product import Product, StockStatus


class ProductRepository:
    """Camada de acesso a dados para produtos do estoque."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(
        self,
        category_id: UUID | None = None,
        status: StockStatus | None = None,
        needs_restock: bool | None = None,
        is_incomplete_data: bool | None = None,
        search: str | None = None,
    ) -> list[Product]:
        stmt = (
            select(Product)
            .options(selectinload(Product.category))
            .order_by(Product.canonical_name.asc())
        )
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if status is not None:
            stmt = stmt.where(Product.stock_status == status)
        if needs_restock is not None:
            stmt = stmt.where(Product.needs_restock == needs_restock)
        if is_incomplete_data is not None:
            stmt = stmt.where(Product.is_incomplete_data == is_incomplete_data)
        if search:
            q = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    Product.canonical_name.ilike(q),
                    Product.normalized_name.ilike(q),
                    Product.raw_main_value.ilike(q),
                )
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, product_id: UUID) -> Product | None:
        stmt = (
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.id == product_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_normalized_name(
        self,
        normalized_name: str,
        category_id: UUID | None = None,
    ) -> Product | None:
        stmt = select(Product).options(selectinload(Product.category)).where(
            Product.normalized_name == normalized_name
        )
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, product: Product) -> Product:
        self.session.add(product)
        await self.session.flush()
        return product

    async def save(self, product: Product) -> Product:
        self.session.add(product)
        await self.session.flush()
        return product

    async def delete(self, product: Product) -> None:
        await self.session.delete(product)
        await self.session.flush()
