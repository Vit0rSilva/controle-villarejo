import secrets
from fastapi import Header, HTTPException, Query, Request, status

from app.core.config import settings


async def verify_webhook_token(
    request: Request,
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    apikey: str | None = Header(default=None, alias="apikey"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    token: str | None = Query(default=None, description="Token secreto do webhook via query param"),
) -> bool:
    """
    Valida o token secreto do Webhook da Evolution API quando fornecido ou quando `REQUIRE_WEBHOOK_TOKEN=True`.
    Se a Evolution API enviar a requisição diretamente sem header customizado e `REQUIRE_WEBHOOK_TOKEN=False`,
    permite a leitura (o filtro estrito de grupo `TARGET_GROUP_JID` e de formato garante a segurança).
    """
    expected = settings.EVOLUTION_WEBHOOK_TOKEN
    candidates: list[str] = []
    if x_webhook_token:
        candidates.append(x_webhook_token.strip())
    if apikey:
        candidates.append(apikey.strip())
    if authorization:
        if authorization.lower().startswith("bearer "):
            candidates.append(authorization[7:].strip())
        else:
            candidates.append(authorization.strip())
    if token:
        candidates.append(token.strip())

    # Se nenhum token foi enviado na requisição e REQUIRE_WEBHOOK_TOKEN for False, permite observar o webhook
    if not candidates and not settings.REQUIRE_WEBHOOK_TOKEN:
        return True

    if not expected:
        return True

    valid_tokens = {expected}
    if settings.EVOLUTION_INSTANCE_TOKEN:
        valid_tokens.add(settings.EVOLUTION_INSTANCE_TOKEN)

    for candidate in candidates:
        for valid in valid_tokens:
            if secrets.compare_digest(candidate, valid):
                return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token de webhook inválido.",
    )
