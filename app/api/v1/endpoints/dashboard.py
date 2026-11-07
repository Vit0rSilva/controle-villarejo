import asyncio
import logging
import time

from fastapi import APIRouter, Query

from app.api.deps import EvolutionServiceDep, StockServiceDep
from app.core.config import settings
from app.schemas.dashboard import DashboardResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_sync_lock = asyncio.Lock()
_last_page_sync_monotonic: float = 0.0
MIN_SYNC_COOLDOWN_SECONDS: float = 5.0


@router.get(
    "",
    response_model=DashboardResponse,
    summary="Retorna resumo consolidado do estoque; se sync=true (ao abrir a página), varre as mensagens do grupo antes",
)
async def get_dashboard(
    stock_service: StockServiceDep,
    evolution_service: EvolutionServiceDep,
    sync: bool = Query(
        default=False,
        description="Se True, varre as mensagens atuais do grupo na Evolution API ao abrir/atualizar a página",
    ),
) -> DashboardResponse:
    global _last_page_sync_monotonic
    if sync and settings.APP_ENV != "testing":
        now_mono = time.monotonic()
        if (now_mono - _last_page_sync_monotonic) >= MIN_SYNC_COOLDOWN_SECONDS and not _sync_lock.locked():
            async with _sync_lock:
                try:
                    sync_res = await evolution_service.sync_current_group_messages(
                        stock_service,
                        force=False,
                    )
                    _last_page_sync_monotonic = time.monotonic()
                    if sync_res.get("total_items_updated", 0) > 0:
                        logger.info(
                            "Varredura ao abrir página atualizou %d itens em %s",
                            sync_res["total_items_updated"],
                            sync_res.get("sections_updated"),
                        )
                except Exception as exc:
                    logger.warning("Aviso na varredura ao abrir página: %s", exc)

    return await stock_service.get_dashboard_data()
