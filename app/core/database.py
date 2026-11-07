import asyncio
import logging
from collections.abc import AsyncGenerator

import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Classe base declarativa para os modelos ORM do SQLAlchemy 2.0."""

    pass


def _build_engine(db_url: str) -> AsyncEngine:
    is_sqlite = db_url.startswith("sqlite")
    kwargs: dict = {
        "echo": False,
        "future": True,
    }
    if not is_sqlite:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return create_async_engine(db_url, **kwargs)


engine: AsyncEngine = _build_engine(settings.DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

_db_initialized: bool = False


async def _ensure_postgres_database_exists(db_url: str, max_retries: int = 10) -> None:
    """
    Conecta ao banco administrativo `postgres` e cria automaticamente o banco de dados alvo
    (ex: `estoque_db`) caso ele ainda não exista. Inclui retry para aguardar inicialização do container.
    """
    if not db_url.startswith("postgresql"):
        return

    parsed = make_url(db_url)
    target_db = parsed.database or "estoque_db"
    host = parsed.host or "localhost"
    port = parsed.port or 5432
    user = parsed.username or "postgres"
    password = parsed.password or ""

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            sys_conn = await asyncpg.connect(
                user=user,
                password=password,
                host=host,
                port=port,
                database="postgres",
                timeout=5.0,
            )
            try:
                exists = await sys_conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1",
                    target_db,
                )
                if not exists:
                    safe_db_name = target_db.replace('"', '""')
                    await sys_conn.execute(f'CREATE DATABASE "{safe_db_name}"')
                    logger.info("Banco de dados PostgreSQL '%s' criado automaticamente!", target_db)
            finally:
                await sys_conn.close()
            return
        except Exception as exc:
            last_err = exc
            if attempt < max_retries and host not in ("localhost", "127.0.0.1"):
                logger.info(
                    "Aguardando container PostgreSQL em %s:%s (tentativa %d/%d)...",
                    host,
                    port,
                    attempt,
                    max_retries,
                )
                await asyncio.sleep(1.5)
            else:
                break

    if last_err is not None:
        raise last_err


async def ensure_database_ready() -> str:
    """
    Ao iniciar a API:
    1. Cria automaticamente o banco de dados no PostgreSQL se não existir (`_ensure_postgres_database_exists`).
    2. Ativa as extensões `pg_trgm` e `unaccent`.
    3. Cria todas as tabelas (`categories`, `products`, `stock_logs`) e índices GIN trigram automaticamente.
    4. Em modo de desenvolvimento local fora do Docker, realiza fallback para SQLite caso o Postgres local não esteja acessível.
    """
    global engine, AsyncSessionLocal, _db_initialized
    if _db_initialized:
        return str(engine.url)

    try:
        if settings.DATABASE_URL.startswith("postgresql"):
            await _ensure_postgres_database_exists(settings.DATABASE_URL)

        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
            if settings.DATABASE_URL.startswith("postgresql"):
                try:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent;"))
                except Exception as ext_exc:
                    logger.warning("Não foi possível ativar extensões pg_trgm/unaccent: %s", ext_exc)

            # Cria todas as tabelas declaradas nos models se não existirem
            await conn.run_sync(Base.metadata.create_all)

            if settings.DATABASE_URL.startswith("postgresql"):
                try:
                    await conn.execute(
                        text("ALTER TYPE stock_status_enum ADD VALUE IF NOT EXISTS 'PORTIONED';")
                    )
                except Exception as enum_exc:
                    logger.warning("Aviso ao atualizar stock_status_enum: %s", enum_exc)

                try:
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_products_normalized_name_trgm "
                            "ON products USING gin (normalized_name gin_trgm_ops);"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_products_canonical_name_trgm "
                            "ON products USING gin (canonical_name gin_trgm_ops);"
                        )
                    )
                except Exception as idx_exc:
                    logger.warning("Não foi possível criar índices GIN trgm: %s", idx_exc)

        _db_initialized = True
        return settings.DATABASE_URL
    except Exception as exc:
        if settings.APP_ENV in ("development", "testing") and not settings.DATABASE_URL.startswith("sqlite"):
            fallback_url = "sqlite+aiosqlite:///./estoque_dev.db"
            logger.warning(
                "PostgreSQL (%s) indisponível (%s). Usando banco de fallback local em modo %s: %s",
                settings.DATABASE_URL,
                exc,
                settings.APP_ENV,
                fallback_url,
            )
            await engine.dispose()
            engine = _build_engine(fallback_url)
            AsyncSessionLocal = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            _db_initialized = True
            return fallback_url
        raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provedor de sessão assíncrona para injeção de dependência."""
    if not _db_initialized:
        await ensure_database_ready()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
