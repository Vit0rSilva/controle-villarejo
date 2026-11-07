from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from app.core.config import settings
from app.schemas.webhook import EvolutionWebhookPayload
from app.services.parser_service import ParserService

if TYPE_CHECKING:
    from app.services.stock_service import StockService

logger = logging.getLogger(__name__)


class EvolutionService:
    """
    Cliente de integração assíncrona com a Evolution API (v1 / v2) em modo EXCLUSIVAMENTE OBSERVADOR (Read-Only no WhatsApp).
    Responsável por:
    1. Fornecer a URL de Webhook pronta para adicionar na Evolution API (e registrar automaticamente via `/webhook/set/{instance}` se o token estiver configurado).
    2. Validar a conexão com a instância usando `EVOLUTION_INSTANCE_TOKEN` (header `apikey`) e resolver o nome da instância.
    3. Ao conectar/iniciar, buscar as mensagens atuais do grupo `557188908550-1544726594@g.us` via `/chat/findMessages/{instance}`,
       filtrar apenas mensagens que seguem o modelo de relatório de estoque e aplicar apenas a mensagem MAIS ATUAL de cada seção (sem misturar mensagens antigas).
    """

    def __init__(
        self,
        base_url: str | None = None,
        instance_name: str | None = None,
        instance_token: str | None = None,
        webhook_token: str | None = None,
        target_group_jid: str | None = None,
        timeout: float = 12.0,
    ) -> None:
        self.base_url = (base_url or settings.EVOLUTION_API_URL).rstrip("/")
        self.instance_name = instance_name or settings.EVOLUTION_INSTANCE_NAME
        self.instance_token = instance_token or settings.EVOLUTION_INSTANCE_TOKEN
        self.webhook_token = webhook_token or settings.EVOLUTION_WEBHOOK_TOKEN
        self.target_group_jid = target_group_jid or settings.TARGET_GROUP_JID
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.instance_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def validate_webhook_token(self, provided_token: str | None) -> bool:
        """Valida em tempo constante o `EVOLUTION_WEBHOOK_TOKEN` recebido."""
        if not self.webhook_token:
            return True
        if not provided_token:
            return not settings.REQUIRE_WEBHOOK_TOKEN
        token_clean = provided_token.strip()
        if token_clean.lower().startswith("bearer "):
            token_clean = token_clean[7:].strip()

        if secrets.compare_digest(token_clean, self.webhook_token):
            return True
        if self.instance_token and secrets.compare_digest(token_clean, self.instance_token):
            return True
        return False

    def get_webhook_configuration_info(self) -> dict[str, Any]:
        """Retorna os dados exatos do Webhook para o usuário colar na Evolution API."""
        return {
            "mode": "READ_ONLY_OBSERVER",
            "target_group_jid": self.target_group_jid,
            "webhook_url_docker_internal": settings.WEBHOOK_PUBLIC_URL,
            "webhook_url_with_token": f"{settings.WEBHOOK_PUBLIC_URL}?token={self.webhook_token}",
            "webhook_url_host": f"http://localhost:8001/api/v1/webhook/evolution?token={self.webhook_token}",
            "required_events": ["MESSAGES_UPSERT"],
            "instructions": (
                "Adicione a URL 'http://villarejo-api:8000/api/v1/webhook/evolution' na aba Webhooks da sua instância "
                "no Evolution API (marcando o evento MESSAGES_UPSERT). O sistema observará exclusivamente o grupo "
                f"'{self.target_group_jid}' e processará apenas mensagens no formato de relatório de estoque."
            ),
        }

    async def validate_and_resolve_instance(self) -> dict[str, Any]:
        """
        Valida a conexão com a Evolution API e descobre/confirma dinamicamente o nome da instância.
        """
        webhook_info = self.get_webhook_configuration_info()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            # 1. Tenta buscar lista de instâncias em /instance/fetchInstances para descobrir instância ativa
            try:
                fetch_resp = await client.get(
                    "/instance/fetchInstances",
                    headers=self._headers(),
                )
                if fetch_resp.status_code == 200:
                    instances = fetch_resp.json()
                    if isinstance(instances, dict):
                        instances = [instances]
                    if isinstance(instances, list) and instances:
                        matched: dict[str, Any] | None = None
                        for item in instances:
                            if not isinstance(item, dict):
                                continue
                            inst_obj = item.get("instance") if isinstance(item.get("instance"), dict) else item
                            name_cand = inst_obj.get("instanceName") or inst_obj.get("name")
                            if name_cand == self.instance_name:
                                matched = inst_obj
                                break
                        if matched is None:
                            # Pega a primeira instância aberta/conectada se o nome padrão não bater
                            for item in instances:
                                if not isinstance(item, dict):
                                    continue
                                inst_obj = item.get("instance") if isinstance(item.get("instance"), dict) else item
                                st = inst_obj.get("connectionStatus") or inst_obj.get("status") or inst_obj.get("state")
                                if st in ("open", "connected"):
                                    matched = inst_obj
                                    break
                            if matched is None:
                                first_item = instances[0]
                                matched = (
                                    first_item.get("instance")
                                    if isinstance(first_item.get("instance"), dict)
                                    else first_item
                                )

                        resolved_name = (
                            matched.get("instanceName")
                            or matched.get("name")
                            or self.instance_name
                        )
                        self.instance_name = resolved_name
                        state = (
                            matched.get("connectionStatus")
                            or matched.get("status")
                            or matched.get("state")
                            or "open"
                        )
                        return {
                            "connected": state in ("open", "connected"),
                            "state": state,
                            "instance_name": resolved_name,
                            "source_endpoint": "/instance/fetchInstances",
                            "webhook_config": webhook_info,
                        }
            except httpx.HTTPError as exc:
                logger.debug("Falha ao consultar fetchInstances: %s", exc)

            # 2. Tenta connectionState/{instance}
            try:
                state_resp = await client.get(
                    f"/instance/connectionState/{self.instance_name}",
                    headers=self._headers(),
                )
                if state_resp.status_code == 200:
                    payload = state_resp.json()
                    instance_data = payload.get("instance") or payload
                    resolved_name = (
                        instance_data.get("instanceName")
                        or instance_data.get("name")
                        or self.instance_name
                    )
                    self.instance_name = resolved_name
                    state = instance_data.get("state") or payload.get("state") or "open"
                    return {
                        "connected": state == "open",
                        "state": state,
                        "instance_name": resolved_name,
                        "source_endpoint": f"/instance/connectionState/{self.instance_name}",
                        "webhook_config": webhook_info,
                    }
            except httpx.HTTPError as exc:
                logger.warning("Evolution API inacessível em %s: %s", self.base_url, exc)
                return {
                    "connected": False,
                    "state": "unreachable",
                    "instance_name": self.instance_name,
                    "webhook_config": webhook_info,
                    "error": str(exc),
                }

        return {
            "connected": False,
            "state": "awaiting_valid_instance_token",
            "instance_name": self.instance_name,
            "webhook_config": webhook_info,
        }

    async def register_webhook_on_evolution(self) -> dict[str, Any]:
        """
        Tenta registrar automaticamente o Webhook na Evolution API via `POST /webhook/set/{instance}`
        em modo observador (`MESSAGES_UPSERT`).
        """
        status_info = await self.validate_and_resolve_instance()
        resolved_instance = status_info.get("instance_name") or self.instance_name
        webhook_url = settings.WEBHOOK_PUBLIC_URL

        body = {
            "webhook": {
                "enabled": True,
                "url": webhook_url,
                "webhookByEvents": False,
                "webhookBase64": False,
                "events": ["MESSAGES_UPSERT"],
            }
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            for payload_variant in (body, body["webhook"]):
                try:
                    resp = await client.post(
                        f"/webhook/set/{resolved_instance}",
                        headers=self._headers(),
                        json=payload_variant,
                    )
                    if resp.status_code in (200, 201):
                        return {
                            "registered": True,
                            "instance_name": resolved_instance,
                            "webhook_url": webhook_url,
                            "response": resp.json(),
                        }
                except httpx.HTTPError as exc:
                    logger.debug("Tentativa de registro automático de webhook falhou: %s", exc)

        return {
            "registered": False,
            "instance_name": resolved_instance,
            "webhook_url": webhook_url,
            "detail": "Configure manualmente a URL no painel da Evolution API ou verifique EVOLUTION_INSTANCE_TOKEN no .env.",
        }

    def _extract_raw_messages_list(self, response_json: Any) -> list[dict[str, Any]]:
        """Extrai a lista de registros de mensagens retornada pelo `/chat/findMessages/{instance}` da Evolution API v1/v2."""
        if isinstance(response_json, list):
            return [m for m in response_json if isinstance(m, dict)]
        if isinstance(response_json, dict):
            msgs = response_json.get("messages")
            if isinstance(msgs, list):
                return [m for m in msgs if isinstance(m, dict)]
            if isinstance(msgs, dict) and isinstance(msgs.get("records"), list):
                return [m for m in msgs["records"] if isinstance(m, dict)]
            if isinstance(response_json.get("records"), list):
                return [m for m in response_json["records"] if isinstance(m, dict)]
            if isinstance(response_json.get("data"), list):
                return [m for m in response_json["data"] if isinstance(m, dict)]
        return []

    async def sync_current_group_messages(
        self,
        stock_service: "StockService",
        limit: int = 200,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Varre as mensagens do grupo `557188908550-1544726594@g.us` na Evolution API (incluindo mensagens editadas):
        1. Filtra exclusivamente mensagens daquele grupo.
        2. Separa relatórios oficiais (Pizzaria por seção e Relação Produtos DiParma), mantendo APENAS o mais recente de cada bloco.
        3. Para mensagens fora do padrão enviadas após os relatórios, verifica apenas se atualizam itens já cadastrados (`allow_create_new=False`).
        4. Em modo automático (`force=False`, varredura de 10m ou abertura de página), ignora mensagens idênticas já processadas para preservar edições manuais recentes.
        """
        status_info = await self.validate_and_resolve_instance()
        if not status_info.get("connected"):
            return {
                "synced": False,
                "reason": "Instância Evolution API ainda não autenticada ou offline",
                "instance_status": status_info,
            }

        resolved_instance = status_info.get("instance_name") or self.instance_name
        query_body = {
            "where": {
                "key": {
                    "remoteJid": self.target_group_jid,
                }
            },
            "limit": limit,
        }

        raw_records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"/chat/findMessages/{resolved_instance}",
                    headers=self._headers(),
                    json=query_body,
                )
                if resp.status_code == 200:
                    raw_records = self._extract_raw_messages_list(resp.json())
            except httpx.HTTPError as exc:
                logger.warning("Erro ao buscar histórico de mensagens do grupo %s: %s", self.target_group_jid, exc)
                return {
                    "synced": False,
                    "reason": f"Erro HTTP ao buscar mensagens: {exc}",
                }

        # Mensagens já ingeridas anteriormente (evita regravar sem necessidade nas varreduras de 10m)
        already_logged_texts: set[str] = set()
        empty_section_names: set[str] = set()
        if not force:
            recent_logs = await stock_service.log_repo.list_recent(limit=120)
            already_logged_texts = {(lg.raw_message or "").strip() for lg in recent_logs if lg.raw_message}
            cats = await stock_service.category_repo.list_all_ordered(include_products=True)
            empty_section_names = {c.name for c in cats if not c.products}

        latest_standard_by_key: dict[str, tuple[datetime, str, str | None, list[str]]] = {}
        loose_candidates: list[tuple[datetime, str, str | None]] = []
        matched_messages_count = 0

        for rec in raw_records:
            payload = EvolutionWebhookPayload(
                event="messages.upsert",
                instance=resolved_instance,
                data=rec,
            )
            text, remote_jid, sender_phone, msg_dt = payload.extract_message_metadata()
            if not text:
                continue
            if remote_jid and remote_jid != self.target_group_jid:
                continue

            parsed = ParserService.parse_message(text)
            if not parsed.items:
                continue

            eff_dt = msg_dt or datetime.now(timezone.utc)
            if parsed.is_standard_pattern:
                matched_messages_count += 1
                if parsed.report_origin == "DIPARMA":
                    report_key = "DIPARMA"
                elif "Sorvetes" in parsed.detected_sections or "Embalagens e Preparos" in parsed.detected_sections:
                    report_key = "PIZZARIA:Embalagens_Sorvetes"
                else:
                    sec_part = ",".join(sorted(parsed.detected_sections)) if parsed.detected_sections else "AUTO"
                    report_key = f"PIZZARIA:{sec_part}"

                existing = latest_standard_by_key.get(report_key)
                if existing is None or eff_dt >= existing[0]:
                    latest_standard_by_key[report_key] = (eff_dt, text, sender_phone, parsed.detected_sections)
            else:
                loose_candidates.append((eff_dt, text, sender_phone))

        processed_sections: list[str] = []
        total_items_updated = 0
        min_standard_dt: datetime | None = None

        # 1. Processa do mais antigo para o mais recente dentre os relatórios padrão atuais de cada bloco
        for _, (msg_dt, text, sender_phone, det_secs) in sorted(latest_standard_by_key.items(), key=lambda x: x[1][0]):
            if min_standard_dt is None or msg_dt > min_standard_dt:
                min_standard_dt = msg_dt

            fills_empty_sec = any(s in empty_section_names for s in det_secs) or (
                not det_secs and bool(empty_section_names)
            )
            if not force and not fills_empty_sec and text.strip() in already_logged_texts:
                continue

            res = await stock_service.process_whatsapp_message(
                raw_message=text,
                instance_name=resolved_instance,
                sender_phone=sender_phone,
                source="WHATSAPP",
                reference_timestamp=msg_dt,
                replace_section_snapshot=True,
                group_jid=self.target_group_jid,
                allow_create_new=True,
            )
            for s in res.affected_sections:
                if s not in processed_sections:
                    processed_sections.append(s)
            total_items_updated += res.parsed_items_count

        # 2. Aplica eventuais atualizações avulsas mais recentes que os relatórios padrão (sem criar novos itens!)
        for msg_dt, text, sender_phone in sorted(loose_candidates, key=lambda x: x[0]):
            if min_standard_dt is not None and msg_dt < min_standard_dt:
                continue
            if not force and text.strip() in already_logged_texts:
                continue
            res = await stock_service.process_whatsapp_message(
                raw_message=text,
                instance_name=resolved_instance,
                sender_phone=sender_phone,
                source="WHATSAPP",
                reference_timestamp=msg_dt,
                replace_section_snapshot=False,
                group_jid=self.target_group_jid,
                allow_create_new=False,
            )
            if res.status == "processed":
                for s in res.affected_sections:
                    if s not in processed_sections:
                        processed_sections.append(s)
                total_items_updated += res.parsed_items_count

        await stock_service.deduplicate_existing_products()

        return {
            "synced": True,
            "instance_name": resolved_instance,
            "group_jid": self.target_group_jid,
            "total_group_messages_scanned": len(raw_records),
            "valid_stock_messages_found": matched_messages_count,
            "sections_updated": processed_sections,
            "total_items_updated": total_items_updated,
        }
