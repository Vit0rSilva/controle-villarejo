from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.category import Category


DEFAULT_CATEGORIES: list[dict] = [
    {
        "name": "Frios",
        "slug": "frios",
        "display_order": 1,
        "keywords": ["frios", "laticinios", "queijos", "embutidos"],
    },
    {
        "name": "Açougue",
        "slug": "acougue",
        "display_order": 2,
        "keywords": ["acougue", "açougue", "carnes", "proteinas", "frango", "camarao", "peixes"],
    },
    {
        "name": "Mercado",
        "slug": "mercado",
        "display_order": 3,
        "keywords": ["mercado", "mercearia", "secos", "molhos", "temperos", "conservas"],
    },
    {
        "name": "Hortifrutis",
        "slug": "hortifrutis",
        "display_order": 4,
        "keywords": ["hortifrutis", "hortifruti", "horti", "frutas", "verduras", "legumes", "para suco", "folhas"],
    },
    {
        "name": "Produtos de Limpeza",
        "slug": "produtos-de-limpeza",
        "display_order": 5,
        "keywords": ["produtos de limpeza", "limpeza", "higiene", "material de limpeza"],
    },
    {
        "name": "Embalagens e Preparos",
        "slug": "embalagens-e-preparos",
        "display_order": 6,
        "keywords": ["embalagens e preparos", "embalagens", "preparos", "caixas", "massas"],
    },
    {
        "name": "Sorvetes",
        "slug": "sorvetes",
        "display_order": 7,
        "keywords": ["sorvetes", "sorvete", "gelados"],
    },
]


class CategoryRepository:
    """Camada de acesso a dados para seções (categories) do estoque."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all_ordered(self, include_products: bool = True) -> list[Category]:
        stmt = select(Category).order_by(Category.display_order.asc(), Category.name.asc())
        if include_products:
            stmt = stmt.options(selectinload(Category.products))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, category_id: UUID, include_products: bool = False) -> Category | None:
        stmt = select(Category).where(Category.id == category_id)
        if include_products:
            stmt = stmt.options(selectinload(Category.products))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Category | None:
        stmt = select(Category).where(Category.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Category | None:
        stmt = select(Category).where(Category.name.ilike(name.strip()))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        name: str,
        slug: str,
        display_order: int = 0,
        keywords: list[str] | None = None,
    ) -> Category:
        category = Category(
            name=name.strip(),
            slug=slug.strip(),
            display_order=display_order,
            keywords=keywords or [],
        )
        self.session.add(category)
        await self.session.flush()
        return category

    async def save(self, category: Category) -> Category:
        self.session.add(category)
        await self.session.flush()
        return category

    async def touch_timestamp(
        self,
        category: Category,
        source: str = "WHATSAPP",
        updated_at: datetime | None = None,
    ) -> Category:
        category.last_updated_at = updated_at or datetime.now(timezone.utc)
        category.last_update_source = source
        self.session.add(category)
        await self.session.flush()
        return category

    async def ensure_default_categories(self) -> list[Category]:
        """Garante que as 7 seções padrão do restaurante existam no banco."""
        existing = await self.list_all_ordered(include_products=False)
        by_slug = {c.slug: c for c in existing}
        created_any = False

        for item in DEFAULT_CATEGORIES:
            if item["slug"] not in by_slug:
                cat = Category(
                    name=item["name"],
                    slug=item["slug"],
                    display_order=item["display_order"],
                    keywords=item["keywords"],
                )
                self.session.add(cat)
                created_any = True

        if created_any:
            await self.session.commit()
            return await self.list_all_ordered(include_products=True)
        return existing
