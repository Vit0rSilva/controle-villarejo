from typing import Any

from fastapi import APIRouter, status

from app.api.deps import EvolutionServiceDep, StockServiceDep, WebhookAuthDep
from app.core.config import settings
from app.schemas.webhook import (
    EvolutionWebhookPayload,
    ManualParseRequest,
    ParseResultResponse,
)
from app.services.parser_service import ParserService

router = APIRouter()


@router.post(
    "/webhook/evolution",
    response_model=ParseResultResponse | dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Observa eventos messages.upsert e messages.update do grupo específico na Evolution API",
)
async def receive_evolution_webhook(
    payload: EvolutionWebhookPayload,
    _auth: WebhookAuthDep,
    stock_service: StockServiceDep,
) -> ParseResultResponse | dict[str, Any]:
    """
    Endpoint receptor do Webhook da Evolution API (Modo Observador Read-Only):
    1. Aceita `messages.upsert` e `messages.update` (para capturar edições de mensagens no WhatsApp).
    2. Filtra estritamente pelo grupo específico `TARGET_GROUP_JID` (`557188908550-1544726594@g.us`).
    3. Se a mensagem está no padrão oficial (Pizzaria ou DiParma), atualiza e permite adicionar novos itens.
    4. Se faltar o padrão na mensagem, verifica apenas se existe item já cadastrado e o atualiza (`allow_create_new=False`).
    """
    normalized_event = payload.event.strip().lower().replace("_", ".")
    if normalized_event not in ("messages.upsert", "messages.update"):
        return {
            "status": "ignored",
            "reason": f"Evento '{payload.event}' não é messages.upsert/messages.update",
            "instance": payload.instance or settings.EVOLUTION_INSTANCE_NAME,
        }

    text, remote_jid, sender_phone, msg_datetime = payload.extract_message_metadata()

    # 1. Filtro estrito de grupo: observa APENAS o grupo 557188908550-1544726594@g.us
    if settings.TARGET_GROUP_JID and remote_jid != settings.TARGET_GROUP_JID:
        return {
            "status": "ignored",
            "reason": f"Chat '{remote_jid}' ignorado. Observando apenas o grupo '{settings.TARGET_GROUP_JID}'.",
            "instance": payload.instance or settings.EVOLUTION_INSTANCE_NAME,
        }

    if not text:
        return {
            "status": "ignored",
            "reason": "Mensagem sem conteúdo textual",
            "instance": payload.instance or settings.EVOLUTION_INSTANCE_NAME,
        }

    parsed = ParserService.parse_message(text)
    if not parsed.items:
        return {
            "status": "ignored",
            "reason": "Mensagem do grupo não possui o formato de relatório de estoque",
            "group_jid": remote_jid,
            "instance": payload.instance or settings.EVOLUTION_INSTANCE_NAME,
        }

    result = await stock_service.process_whatsapp_message(
        raw_message=text,
        instance_name=payload.instance or settings.EVOLUTION_INSTANCE_NAME,
        sender_phone=sender_phone,
        source="WHATSAPP",
        reference_timestamp=msg_datetime,
        replace_section_snapshot=parsed.is_standard_pattern,
        group_jid=remote_jid,
        allow_create_new=parsed.is_standard_pattern,
    )
    if result.status == "ignored":
        return {
            "status": "ignored",
            "reason": "Mensagem fora do padrão e nenhum item já cadastrado foi identificado",
            "group_jid": remote_jid,
            "instance": payload.instance or settings.EVOLUTION_INSTANCE_NAME,
        }
    return result


@router.post(
    "/stock/parse-manual",
    response_model=ParseResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Processa manualmente uma mensagem de estoque colada no painel web",
)
async def parse_manual_stock_message(
    payload: ManualParseRequest,
    stock_service: StockServiceDep,
) -> ParseResultResponse:
    """
    Permite colar uma mensagem do WhatsApp manualmente direto no site.
    Segue a mesma regra: novos itens só são criados se estiverem no padrão de mensagem oficial;
    caso contrário, atualiza apenas produtos já cadastrados.
    """
    return await stock_service.process_whatsapp_message(
        raw_message=payload.raw_message,
        instance_name=settings.EVOLUTION_INSTANCE_NAME,
        sender_phone=payload.sender_phone or "WEB_MANUAL",
        default_section_name=payload.default_section_name,
        source="WHATSAPP",
        replace_section_snapshot=payload.replace_section_snapshot,
        group_jid=settings.TARGET_GROUP_JID,
    )


@router.post(
    "/webhook/sync-group",
    summary="Força varredura imediata das mensagens do grupo 557188908550-1544726594@g.us na Evolution API",
)
async def sync_group_messages_now(
    stock_service: StockServiceDep,
    evolution_service: EvolutionServiceDep,
) -> dict[str, Any]:
    return await evolution_service.sync_current_group_messages(stock_service, force=True)


@router.post(
    "/webhook/register",
    summary="Registra automaticamente a URL do Webhook na instância da Evolution API",
)
async def register_webhook_in_evolution(
    evolution_service: EvolutionServiceDep,
) -> dict[str, Any]:
    return await evolution_service.register_webhook_on_evolution()


@router.get(
    "/webhook/instance-status",
    summary="Retorna status da Evolution API e a URL do Webhook pronta para configurar",
)
async def check_evolution_instance_status(
    evolution_service: EvolutionServiceDep,
) -> dict[str, Any]:
    return await evolution_service.validate_and_resolve_instance()
