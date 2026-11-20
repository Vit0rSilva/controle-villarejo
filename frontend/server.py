import base64
import hashlib
import hmac
import os
import secrets
import time
import ipaddress
from urllib.parse import parse_qs
from pathlib import Path

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

API_BACKEND_URL = os.getenv("API_BACKEND_URL", "http://villarejo-api:8000").rstrip("/")
INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "app" / "templates" / "index.html"
SESSION_COOKIE = "villarejo_session"
SESSION_TTL_SECONDS = max(900, int(os.getenv("VILLAREJO_SESSION_TTL_SECONDS", "28800")))
ADMIN_USERNAME = os.getenv("VILLAREJO_ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD_HASH = os.getenv("VILLAREJO_ADMIN_PASSWORD_HASH", "").strip()
AUTH_SECRET = os.getenv("VILLAREJO_AUTH_SECRET", "").strip()

_MAX_LOGIN_FAILURES = int(os.getenv("VILLAREJO_LOGIN_FAILURE_LIMIT", "5"))
_PERMANENT_LOGIN_FAILURES = int(os.getenv("VILLAREJO_LOGIN_PERMANENT_FAILURE_LIMIT", "20"))
_LOGIN_WINDOW_SECONDS = int(os.getenv("VILLAREJO_LOGIN_WINDOW_SECONDS", "900"))
REDIS_URL = os.getenv("VILLAREJO_SECURITY_REDIS_URL", "redis://backend-redis:6379/3")
_redis_client: redis.Redis | None = None

LOGIN_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Entrar • Villarejo</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f6f8;color:#20252b;font:16px system-ui,-apple-system,Segoe UI,sans-serif}
.card{width:min(420px,calc(100% - 32px));background:#fff;border:1px solid #e1e5ea;border-radius:18px;padding:32px;box-shadow:0 18px 55px #18222d18}.brand{display:flex;align-items:center;gap:12px;margin-bottom:26px}.mark{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:#1f2937;color:#fff;font-weight:800}.muted{color:#697586;font-size:14px;margin-top:4px}label{display:block;font-size:13px;font-weight:650;margin:18px 0 7px}input{width:100%;height:46px;border:1px solid #d4d9df;border-radius:10px;padding:0 13px;font:inherit}input:focus{outline:3px solid #2563eb22;border-color:#2563eb}button{width:100%;height:46px;border:0;border-radius:10px;background:#1f2937;color:#fff;font-weight:700;font-size:15px;margin-top:22px;cursor:pointer}button:hover{background:#111827}.error{background:#fff1f2;border:1px solid #fecdd3;color:#be123c;border-radius:9px;padding:10px 12px;font-size:13px;margin-bottom:4px}.small{margin-top:18px;color:#8a94a3;font-size:12px;text-align:center}
</style></head><body><main class="card"><div class="brand"><div class="mark">V</div><div><strong>Controle Villarejo</strong><div class="muted">Acesso administrativo</div></div></div>
{error}<form method="post" action="/auth/login" autocomplete="on"><label for="username">Usuário</label><input id="username" name="username" type="text" autocomplete="username" required autofocus><label for="password">Senha</label><input id="password" name="password" type="password" autocomplete="current-password" required><button type="submit">Entrar</button></form><div class="small">Acesso restrito. Atividade registrada.</div></main></body></html>"""

frontend_app = FastAPI(title="Controle Villarejo - Frontend Server", docs_url=None, redoc_url=None)


@frontend_app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _password_matches(password: str) -> bool:
    """Valida hash PBKDF2 no formato pbkdf2_sha256$iter$salt$hash."""
    try:
        algorithm, iterations, salt, expected = ADMIN_PASSWORD_HASH.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt_bytes = base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
        calculated = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, int(iterations))
        return hmac.compare_digest(_b64(calculated), expected)
    except (ValueError, TypeError):
        return False


def _session_value(username: str, expires_at: int) -> str:
    payload = f"{username}.{expires_at}.{secrets.token_urlsafe(16)}"
    signature = hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{_b64(payload.encode())}.{_b64(signature)}"


def _valid_session(value: str | None) -> bool:
    if not value or not AUTH_SECRET or not ADMIN_USERNAME:
        return False
    try:
        encoded_payload, encoded_signature = value.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4)).decode()
        expected_signature = hmac.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
        provided_signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        if not hmac.compare_digest(provided_signature, expected_signature):
            return False
        username, expires_at, _nonce = payload.split(".", 2)
        return username == ADMIN_USERNAME and int(expires_at) > int(time.time())
    except (ValueError, TypeError, UnicodeDecodeError):
        return False


def _client_ip(request: Request) -> str:
    for value in (request.headers.get("cf-connecting-ip"), request.headers.get("x-real-ip"), request.client.host if request.client else None):
        try:
            if value:
                return str(ipaddress.ip_address(value.strip()))
        except ValueError:
            continue
    return "unknown"


async def _redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception:
        _redis_client = None
        return None


async def _login_is_blocked(client_ip: str) -> tuple[bool, int]:
    client = await _redis()
    if client is None or client_ip == "unknown":
        return False, 0
    if await client.exists(f"villarejo:login:blocked:{client_ip}"):
        return True, 0
    ttl = await client.ttl(f"villarejo:login:failures:{client_ip}")
    count = int(await client.get(f"villarejo:login:failures:{client_ip}") or 0)
    return count >= _MAX_LOGIN_FAILURES, max(1, ttl)


async def _record_login_failure(client_ip: str) -> bool:
    client = await _redis()
    if client is None or client_ip == "unknown":
        return False
    key = f"villarejo:login:failures:{client_ip}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, _LOGIN_WINDOW_SECONDS)
    if count >= _PERMANENT_LOGIN_FAILURES:
        await client.set(f"villarejo:login:blocked:{client_ip}", "1")
        return True
    return False


async def _record_login_success(client_ip: str) -> None:
    client = await _redis()
    if client is not None and client_ip != "unknown":
        await client.delete(f"villarejo:login:failures:{client_ip}")


def _login_page(error: str = "") -> HTMLResponse:
    escaped_error = "" if not error else f'<div class="error">{error}</div>'
    return HTMLResponse(LOGIN_HTML.replace("{error}", escaped_error), headers={"Cache-Control": "no-store"})


@frontend_app.get("/login", include_in_schema=False)
async def login_page() -> HTMLResponse:
    return _login_page()


@frontend_app.post("/auth/login", include_in_schema=False)
async def login(request: Request) -> Response:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD_HASH or not AUTH_SECRET:
        return _login_page("O acesso administrativo não está configurado no servidor.")
    remote_ip = _client_ip(request)
    blocked, ttl = await _login_is_blocked(remote_ip)
    if blocked:
        return _login_page("Este acesso foi temporariamente bloqueado por excesso de tentativas.")
    body = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    username = body.get("username", [""])[0].strip()
    password = body.get("password", [""])[0]
    if not hmac.compare_digest(username, ADMIN_USERNAME) or not _password_matches(password):
        permanent = await _record_login_failure(remote_ip)
        if permanent:
            return _login_page("Este IP foi bloqueado permanentemente por tentativas repetidas.")
        return _login_page("Usuário ou senha inválidos.")
    await _record_login_success(remote_ip)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        _session_value(ADMIN_USERNAME, int(time.time()) + SESSION_TTL_SECONDS),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


@frontend_app.post("/auth/logout", include_in_schema=False)
async def logout() -> Response:
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@frontend_app.get("/")
async def serve_index(request: Request) -> Response:
    if not _valid_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse(INDEX_HTML_PATH, media_type="text/html")


@frontend_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_to_api(request: Request, path: str) -> Response:
    """Encaminha chamadas /api/*, /health, /docs e /openapi.json para o container villarejo-api."""
    if path == "health":
        pass
    elif path.startswith("auth/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    elif not _valid_session(request.cookies.get(SESSION_COOKIE)):
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return JSONResponse({"detail": "Autenticação necessária"}, status_code=status.HTTP_401_UNAUTHORIZED)
    target_url = f"{API_BACKEND_URL}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "connection")
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method=request.method,
            url=target_url,
            content=body,
            headers=headers,
        )

    excluded_resp_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    response_headers = {
        k: v for k, v in resp.headers.items() if k.lower() not in excluded_resp_headers
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )
