import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.v1.router import api_router
from app.core import database
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.repositories.category_repository import CategoryRepository
from app.repositories.product_repository import ProductRepository
from app.services.evolution_service import EvolutionService
from app.services.stock_service import StockService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def _periodic_group_sync_loop() -> None:
    """
    Tarefa em background que varre automaticamente as mensagens do grupo na Evolution API
    a cada `GROUP_SYNC_INTERVAL_MINUTES` minutos (padrão: 10 em 10 minutos).
    """
    interval_seconds = max(60, settings.GROUP_SYNC_INTERVAL_MINUTES * 60)
    logger.info(
        "Varredura automática agendada a cada %d minutos para o grupo '%s'.",
        settings.GROUP_SYNC_INTERVAL_MINUTES,
        settings.TARGET_GROUP_JID,
    )
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with database.AsyncSessionLocal() as session:
                evo_service = EvolutionService()
                stock_service = StockService(session)
                sync_res = await evo_service.sync_current_group_messages(
                    stock_service,
                    force=False,
                )
                if sync_res.get("synced"):
                    updated = sync_res.get("total_items_updated", 0)
                    if updated > 0:
                        logger.info(
                            "Varredura periódica (10m) atualizou %d itens nas seções %s",
                            updated,
                            sync_res.get("sections_updated"),
                        )
                    else:
                        logger.info("Varredura periódica (10m) concluída: nenhuma nova alteração no grupo.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Erro durante varredura periódica do grupo: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação:
    1. Cria/atualiza automaticamente o banco de dados, extensões e enum (`PORTIONED`).
    2. Garante as seções padrão e consolida eventuais itens duplicados.
    3. Executa varredura inicial no grupo `557188908550-1544726594@g.us` na Evolution API.
    4. Inicia loop de varredura automática de 10 em 10 minutos.
    """
    active_db_url = await database.ensure_database_ready()
    logger.info("Banco de dados e tabelas prontos em: %s", active_db_url)
    logger.info(
        "Modo Observador ativo para o grupo '%s' | Webhook URL: %s",
        settings.TARGET_GROUP_JID,
        settings.WEBHOOK_PUBLIC_URL,
    )

    periodic_task: asyncio.Task | None = None

    async with database.AsyncSessionLocal() as session:
        cat_repo = CategoryRepository(session)
        await cat_repo.ensure_default_categories()

        if settings.APP_ENV != "testing":
            evo_service = EvolutionService()
            stock_service = StockService(session)
            await stock_service.deduplicate_existing_products()

            try:
                sync_res = await evo_service.sync_current_group_messages(
                    stock_service,
                    force=True,
                )
                if sync_res.get("synced") and sync_res.get("total_items_updated", 0) > 0:
                    logger.info(
                        "Sincronização inicial com grupo %s concluída: %d itens em %s",
                        settings.TARGET_GROUP_JID,
                        sync_res["total_items_updated"],
                        sync_res["sections_updated"],
                    )
            except Exception as sync_exc:
                logger.warning("Não foi possível sincronizar histórico inicial com Evolution API: %s", sync_exc)

            if settings.AUTO_SEED_ON_STARTUP:
                prod_repo = ProductRepository(session)
                existing_products = await prod_repo.list_all()
                if not existing_products:
                    logger.info("Populando estado inicial com os relatórios atuais do grupo...")
                    from seed import run_seed

                    await run_seed(clear_existing=True)

    if settings.APP_ENV != "testing":
        periodic_task = asyncio.create_task(_periodic_group_sync_loop())

    try:
        yield
    finally:
        if periodic_task is not None:
            periodic_task.cancel()
            with suppress(asyncio.CancelledError):
                await periodic_task
        await database.engine.dispose()


app = FastAPI(
    title="Controle Villarejo - Estoque Automatizado via WhatsApp (Evolution API)",
    description=(
        f"Observador exclusivo do grupo '{settings.TARGET_GROUP_JID}' via Webhook e varredura a cada 10m, "
        "unificando Pizzaria e DiParma sem duplicidades."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix="/api/v1")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard_ui(request: Request) -> HTMLResponse:
    """Renderiza o Painel Web responsivo de Controle de Estoque."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_env": settings.APP_ENV,
            "stale_hours": settings.STALE_SECTION_HOURS,
        },
    )


@app.get("/health", tags=["Health"])
async def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.APP_ENV,
        "target_group_jid": settings.TARGET_GROUP_JID,
        "webhook_url": settings.WEBHOOK_PUBLIC_URL,
    }
