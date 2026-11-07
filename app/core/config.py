from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações globais da aplicação carregadas e validadas via variáveis de ambiente (.env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/estoque_db",
        description="URL de conexão assíncrona do banco de dados PostgreSQL 16+",
    )

    # Evolution API Configuration
    EVOLUTION_API_URL: str = Field(
        default="http://localhost:8080",
        description="URL base da Evolution API",
    )
    EVOLUTION_INSTANCE_NAME: str = Field(
        default="villarejo_estoque",
        description="Nome da instância configurada na Evolution API",
    )
    EVOLUTION_INSTANCE_TOKEN: str = Field(
        default="token_da_instancia_aqui",
        description="Token/apikey da instância na Evolution API",
    )
    EVOLUTION_WEBHOOK_TOKEN: str = Field(
        default="token_secreto_do_webhook_aqui",
        description="Token secreto para autenticação das requisições de Webhook",
    )
    REQUIRE_WEBHOOK_TOKEN: bool = Field(
        default=False,
        description="Se False, aceita chamadas do Webhook da Evolution API mesmo sem header de token customizado",
    )
    TARGET_GROUP_JID: str = Field(
        default="557188908550-1544726594@g.us",
        description="JID do grupo específico do WhatsApp que deve ser observado exclusivamente",
    )
    WEBHOOK_PUBLIC_URL: str = Field(
        default="http://villarejo-api:8000/api/v1/webhook/evolution",
        description="URL do Webhook que a Evolution API deve chamar ao receber mensagens",
    )

    # Application
    APP_ENV: Literal["development", "staging", "production", "testing"] = Field(
        default="development",
        description="Ambiente de execução",
    )
    STALE_SECTION_HOURS: int = Field(
        default=24,
        ge=1,
        description="Limite em horas para considerar uma seção em atraso de atualização",
    )
    FUZZY_MATCH_THRESHOLD: int = Field(
        default=82,
        ge=50,
        le=100,
        description="Score mínimo (0-100) para considerar similaridade de nome via RapidFuzz",
    )
    AUTO_SEED_ON_STARTUP: bool = Field(
        default=True,
        description="Se True, sincroniza mensagens atuais da Evolution API ou carrega o estado inicial ao subir",
    )
    GROUP_SYNC_INTERVAL_MINUTES: int = Field(
        default=10,
        ge=1,
        description="Intervalo em minutos para varredura automática das mensagens do grupo na Evolution API",
    )
    PLENTY_PORTIONS_THRESHOLD: int = Field(
        default=6,
        ge=2,
        description="Quantidade mínima de porções para considerar 'bastante porção' (azul) quando unidade fechada é 00",
    )

    @field_validator("EVOLUTION_API_URL")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
