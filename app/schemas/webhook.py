from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class EvolutionMessageKey(BaseModel):
    model_config = ConfigDict(extra="allow")

    remoteJid: str | None = None
    fromMe: bool | None = False
    id: str | None = None
    participant: str | None = None


class EvolutionExtendedTextMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str | None = None


class EvolutionMessageContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    conversation: str | None = None
    extendedTextMessage: EvolutionExtendedTextMessage | dict[str, Any] | None = None


class EvolutionWebhookData(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: EvolutionMessageKey | dict[str, Any] | None = None
    pushName: str | None = None
    message: EvolutionMessageContent | dict[str, Any] | None = None
    messageType: str | None = None
    messageTimestamp: int | str | None = None


class EvolutionWebhookPayload(BaseModel):
    """
    Payload recebido no endpoint POST /api/v1/webhook/evolution para eventos da Evolution API
    (especialmente `messages.upsert`).
    """

    model_config = ConfigDict(extra="allow")

    event: str = Field(..., description="Tipo de evento da Evolution API, ex: messages.upsert")
    instance: str | None = Field(default=None, description="Nome da instância na Evolution API")
    data: EvolutionWebhookData | dict[str, Any] | list[dict[str, Any]] | None = None
    sender: str | None = None

    def extract_message_metadata(self) -> tuple[str | None, str | None, str | None, datetime | None]:
        """
        Extrai de forma resiliente:
        - `text`: conteúdo textual da mensagem
        - `remote_jid`: JID do grupo ou conversa (ex: '557188908550-1544726594@g.us')
        - `sender_phone`: participante que enviou a mensagem
        - `msg_datetime`: data/hora da mensagem convertida para UTC
        """
        data_obj: dict[str, Any] = {}
        if isinstance(self.data, EvolutionWebhookData):
            data_obj = self.data.model_dump()
        elif isinstance(self.data, dict):
            if "messages" in self.data and isinstance(self.data["messages"], list) and self.data["messages"]:
                first = self.data["messages"][0]
                if isinstance(first, dict):
                    data_obj = first
            else:
                data_obj = self.data
        elif isinstance(self.data, list) and self.data:
            first = self.data[0]
            if isinstance(first, dict):
                data_obj = first

        key_obj = data_obj.get("key") or {}
        if not isinstance(key_obj, dict):
            key_obj = {}

        remote_jid = key_obj.get("remoteJid") or data_obj.get("remoteJid")
        sender_phone = (
            key_obj.get("participant")
            or remote_jid
            or self.sender
        )

        # Extração do timestamp da mensagem
        raw_ts = data_obj.get("messageTimestamp")
        msg_datetime: datetime | None = None
        if raw_ts is not None:
            try:
                ts_int = int(raw_ts)
                if ts_int > 1_000_000_000_000:
                    ts_int = ts_int // 1000
                msg_datetime = datetime.fromtimestamp(ts_int, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                msg_datetime = None

        # Extração do texto da mensagem (incluindo mensagens editadas via protocolMessage.editedMessage)
        msg_obj = data_obj.get("message") or {}
        if not isinstance(msg_obj, dict):
            msg_obj = {}

        # Se for mensagem editada (protocolMessage / editedMessage), navega até o conteúdo interno
        proto_msg = msg_obj.get("protocolMessage")
        if isinstance(proto_msg, dict):
            proto_key = proto_msg.get("key")
            if isinstance(proto_key, dict):
                if not remote_jid:
                    remote_jid = proto_key.get("remoteJid")
                if not sender_phone:
                    sender_phone = proto_key.get("participant") or remote_jid
            edited_inner = proto_msg.get("editedMessage")
            if isinstance(edited_inner, dict):
                msg_obj = edited_inner

        edited_wrap = msg_obj.get("editedMessage")
        if isinstance(edited_wrap, dict):
            inner_msg = edited_wrap.get("message")
            if isinstance(inner_msg, dict):
                inner_proto = inner_msg.get("protocolMessage")
                if isinstance(inner_proto, dict) and isinstance(inner_proto.get("editedMessage"), dict):
                    msg_obj = inner_proto["editedMessage"]
                else:
                    msg_obj = inner_msg
            else:
                msg_obj = edited_wrap

        ephemeral_wrap = msg_obj.get("ephemeralMessage")
        if isinstance(ephemeral_wrap, dict) and isinstance(ephemeral_wrap.get("message"), dict):
            msg_obj = ephemeral_wrap["message"]

        text = msg_obj.get("conversation")
        if not text:
            ext = msg_obj.get("extendedTextMessage")
            if isinstance(ext, dict):
                text = ext.get("text")
        if not text:
            img_msg = msg_obj.get("imageMessage")
            if isinstance(img_msg, dict):
                text = img_msg.get("caption")
        if not text and isinstance(data_obj.get("body"), str):
            text = data_obj.get("body")
        if not text and isinstance(data_obj.get("text"), str):
            text = data_obj.get("text")

        clean_text = text.strip() if isinstance(text, str) and text.strip() else None
        return clean_text, remote_jid, sender_phone, msg_datetime

    def extract_text_and_sender(self) -> tuple[str | None, str | None]:
        text, _, sender_phone, _ = self.extract_message_metadata()
        return text, sender_phone


class ManualParseRequest(BaseModel):
    """Payload para processamento manual de mensagem colada diretamente no painel web."""

    raw_message: str = Field(..., min_length=2, description="Texto bruto copiado do WhatsApp")
    default_section_name: str | None = Field(
        default=None,
        description="Seção forçada/padrão caso a mensagem não possua cabeçalho explícito",
    )
    sender_phone: str | None = Field(default="WEB_MANUAL", description="Identificador da origem")
    replace_section_snapshot: bool = Field(
        default=True,
        description="Se True, substitui os produtos da seção pelo retrato atual da mensagem sem misturar antigos",
    )


class ParseResultResponse(BaseModel):
    """Resposta detalhada após o processamento de uma mensagem de estoque."""

    status: str = "processed"
    instance_name: str
    group_jid: str | None = None
    affected_sections: list[str]
    parsed_items_count: int
    created_products_count: int
    updated_products_count: int
    incomplete_items_count: int
    critical_items_count: int
    warning_items_count: int
    unrecognized_lines: list[str]
    log_id: str | None = None
