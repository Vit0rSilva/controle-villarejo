from fastapi import APIRouter

from app.api.v1.endpoints import dashboard, products, sections, webhook

api_router = APIRouter()

api_router.include_router(webhook.router, tags=["Webhook & Parser Manual"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(products.router, prefix="/products", tags=["Products"])
api_router.include_router(sections.router, prefix="/sections", tags=["Sections"])
