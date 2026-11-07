import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse

API_BACKEND_URL = os.getenv("API_BACKEND_URL", "http://villarejo-api:8000").rstrip("/")
INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "app" / "templates" / "index.html"

frontend_app = FastAPI(title="Controle Villarejo - Frontend Server", docs_url=None, redoc_url=None)


@frontend_app.get("/")
async def serve_index() -> FileResponse:
    return FileResponse(INDEX_HTML_PATH, media_type="text/html")


@frontend_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_to_api(request: Request, path: str) -> Response:
    """Encaminha chamadas /api/*, /health, /docs e /openapi.json para o container villarejo-api."""
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
