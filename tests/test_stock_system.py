from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.core.config import settings
from app.core.database import Base
from app.main import app
from app.models.product import Product, StockStatus
from app.repositories.category_repository import CategoryRepository
from app.repositories.product_repository import ProductRepository
from app.services.evolution_service import EvolutionService
from app.services.fuzzy_service import FuzzyService
from app.services.parser_service import ParserService
from app.services.stock_service import StockService
from seed import REAL_RESTAURANT_MESSAGES


@pytest.fixture
async def db_session():
    """Cria um banco em memória isolado para cada teste."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with TestSessionLocal() as session:
        yield session

    await test_engine.dispose()


@pytest.fixture
async def api_client(db_session: AsyncSession):
    """Cliente HTTP assíncrono acoplado à sessão de teste."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


def test_fuzzy_service_normalization_and_units():
    assert FuzzyService.normalize_text("Cifff") == "cif"
    assert FuzzyService.normalize_text("Creme cheese") == "cream cheese"
    assert FuzzyService.normalize_unit("porca") == "porcoes"
    assert FuzzyService.normalize_unit("porções") == "porcoes"
    assert FuzzyService.normalize_unit("uni") == "unidades"
    assert FuzzyService.normalize_unit("pct") == "pacotes"
    assert FuzzyService.normalize_unit("pé") == "pes"
    assert FuzzyService.normalize_inline_terms("100 porca") == "100 porções"
    assert FuzzyService.normalize_inline_terms("temm") == "Tem"


def test_parser_single_line_and_multiline_real_models():
    # Testa o texto colado em linha única com duplicata de Açougue (deve manter apenas o mais recente)
    raw_acougue = (
        "AÇOUGUE ● Carne do Sol : 00 🥩 • 00 Porções de 100g • 13 Porções de petisco 300 Cozida: 00 "
        "● Carne Seca: 2kg 25 porções de 100g ● Costelinha: 00🍖 06 porções de 100g • Cozida: 00 "
        "● Frango 2kg 🐔 • 30 Porções de 100 Cozido: 00 ● Camarão:🦐 11kg porções: Tem "
        "● Salmão: 00 peça: 🐠 08 Porções 150g 00 Porções 100g Porções de petisco 300 Cozida: 00 "
        "● Carne Seca: 00 33 porções de 100g ● Costelinha: 00🍖 09 porções de 100g • Cozida: 00 "
        "● Frango 7kg 🐔 • 34 Porções de 100 Cozido: 01 panela em produção ● Camarão:🦐 7kg porções: Tem "
        "● Salmão: 01 peça: 🐠 03 Porções 150g 01 Porções 100g"
    )
    parsed = ParserService.parse_message(raw_acougue)
    assert parsed.detected_sections == ["Açougue"]
    assert len(parsed.items) == 6
    assert parsed.unrecognized_lines == []

    by_name = {it.canonical_candidate: it for it in parsed.items}
    assert by_name["Carne Seca"].raw_main_value == "00"
    assert by_name["Carne Seca"].sub_attributes["porcoes"] == ["33 porções de 100g"]
    assert by_name["Frango"].raw_main_value == "7kg"
    assert by_name["Frango"].sub_attributes["cozido"] == "01 panela em produção"
    assert by_name["Salmão"].raw_main_value == "01 peça:"
    assert by_name["Salmão"].sub_attributes["porcoes"] == ["03 Porções 150g", "01 Porções 100g"]


def test_is_valid_stock_report_filter():
    assert ParserService.is_valid_stock_report_message("Bom dia pessoal, alguém viu a chave?") is False
    assert ParserService.is_valid_stock_report_message("Ok, já estou indo pro restaurante") is False
    assert ParserService.is_valid_stock_report_message(REAL_RESTAURANT_MESSAGES[0][1]) is True
    assert ParserService.is_valid_stock_report_message(REAL_RESTAURANT_MESSAGES[1][1]) is True
    assert ParserService.is_valid_stock_report_message(REAL_RESTAURANT_MESSAGES[2][1]) is True
    assert ParserService.is_valid_stock_report_message(REAL_RESTAURANT_MESSAGES[3][1]) is True


@pytest.mark.asyncio
async def test_no_mixing_between_old_and_current_section_messages(db_session: AsyncSession):
    stock_service = StockService(db_session)
    prod_repo = ProductRepository(db_session)

    # 1. Envia uma mensagem antiga de Açougue com valores antigos + um produto extra "Picanha Antiga"
    old_msg = """AÇOUGUE
● Carne Seca: 2kg
25 porções de 100g
● Frango 2kg
• 30 Porções de 100
● Camarão: 11kg
● Picanha Antiga: 5kg"""
    await stock_service.process_whatsapp_message(raw_message=old_msg, replace_section_snapshot=True)

    # 2. Envia a mensagem atual de Açougue (sem "Picanha Antiga" e com valores atualizados)
    current_msg = REAL_RESTAURANT_MESSAGES[0][1]
    await stock_service.process_whatsapp_message(raw_message=current_msg, replace_section_snapshot=True)

    all_prods = await prod_repo.list_all()
    names = {p.canonical_name: p for p in all_prods}

    # "Picanha Antiga" deve ter sido substituída (não pode misturar com a mensagem atual!)
    assert "Picanha Antiga" not in names
    assert len(all_prods) == 6
    assert names["Carne Seca"].raw_main_value == "00"
    assert names["Frango"].raw_main_value == "7kg"
    assert names["Camarão"].raw_main_value == "7kg"


@pytest.mark.asyncio
async def test_webhook_group_and_format_filtering(api_client: AsyncClient):
    # 1. Mensagem de outro grupo ou conversa privada deve ser ignorada
    wrong_group_payload = {
        "event": "messages.upsert",
        "instance": "villarejo_estoque",
        "data": {
            "key": {"remoteJid": "5511999999999@s.whatsapp.net"},
            "message": {"conversation": REAL_RESTAURANT_MESSAGES[0][1]},
        },
    }
    r_wrong = await api_client.post("/api/v1/webhook/evolution", json=wrong_group_payload)
    assert r_wrong.status_code == 200
    assert r_wrong.json()["status"] == "ignored"
    assert "557188908550-1544726594@g.us" in r_wrong.json()["reason"]

    # 2. Mensagem no grupo correto (557188908550-1544726594@g.us), mas que é conversa comum (fora do modelo) -> ignorada!
    chat_payload = {
        "event": "messages.upsert",
        "instance": "villarejo_estoque",
        "data": {
            "key": {"remoteJid": "557188908550-1544726594@g.us", "participant": "5571988887777@s.whatsapp.net"},
            "message": {"conversation": "Bom dia galera, já abri a loja!"},
        },
    }
    r_chat = await api_client.post("/api/v1/webhook/evolution", json=chat_payload)
    assert r_chat.status_code == 200
    assert r_chat.json()["status"] == "ignored"

    # 3. Mensagem no grupo correto E no formato de relatório -> processada e atualiza o painel!
    valid_payload = {
        "event": "messages.upsert",
        "instance": "villarejo_estoque",
        "data": {
            "key": {"remoteJid": "557188908550-1544726594@g.us", "participant": "5571988887777@s.whatsapp.net"},
            "message": {"conversation": REAL_RESTAURANT_MESSAGES[1][1]},
        },
    }
    r_valid = await api_client.post("/api/v1/webhook/evolution", json=valid_payload)
    assert r_valid.status_code == 200
    body = r_valid.json()
    assert body["status"] == "processed"
    assert body["affected_sections"] == ["Frios"]
    assert body["parsed_items_count"] == 22


def test_evolution_service_webhook_info():
    evo = EvolutionService()
    info = evo.get_webhook_configuration_info()
    assert info["mode"] == "READ_ONLY_OBSERVER"
    assert info["target_group_jid"] == "557188908550-1544726594@g.us"
    assert "http://villarejo-api:8000/api/v1/webhook/evolution" in info["webhook_url_docker_internal"]


def test_portioned_blue_vs_warning_yellow_and_critical_rules():
    # 1. Fechado 00, mas com BASTANTE porção (35 de 100g / 17 de 100g / 20 de 80g) -> PORTIONED (Azul), não Pouco!
    status_bacon, restock_bacon, _ = StockService.evaluate_stock_status(
        raw_main_value="00",
        numeric_quantity=0,
        sub_attributes={"porcoes": ["35 de 100g"]},
    )
    assert status_bacon == StockStatus.PORTIONED
    assert restock_bacon is False

    status_peito, _, _ = StockService.evaluate_stock_status(
        raw_main_value="00",
        numeric_quantity=0,
        sub_attributes={"porcoes": ["17 de 100g"]},
    )
    assert status_peito == StockStatus.PORTIONED

    status_pepperoni, _, _ = StockService.evaluate_stock_status(
        raw_main_value="00",
        numeric_quantity=0,
        sub_attributes={"porcoes": ["Porções 20 Porções de 80g"]},
    )
    assert status_pepperoni == StockStatus.PORTIONED

    # 2. Fechado 00 e quantidade pequena de porções (<= 5) -> WARNING (Amarelo / Pouco)
    status_few, restock_few, _ = StockService.evaluate_stock_status(
        raw_main_value="00",
        numeric_quantity=0,
        sub_attributes={"porcoes": ["03 de 100g"]},
    )
    assert status_few == StockStatus.WARNING
    assert restock_few is True

    # 3. Tem "pouco" ou "abaixo de meio" na frase -> WARNING (Amarelo / Pouco)
    status_pouco_main, _, _ = StockService.evaluate_stock_status(
        raw_main_value="Abaixo de meio caixote",
        numeric_quantity=None,
        sub_attributes={},
    )
    assert status_pouco_main == StockStatus.WARNING

    status_pouco_sub, _, _ = StockService.evaluate_stock_status(
        raw_main_value="00",
        numeric_quantity=0,
        sub_attributes={"porcoes": ["20 porções (pouco)"]},
    )
    assert status_pouco_sub == StockStatus.WARNING

    # 4. Zerado total ou "Trazer" -> CRITICAL (Vermelho / Em Falta)
    status_zero, restock_zero, _ = StockService.evaluate_stock_status(
        raw_main_value="00 unidade",
        numeric_quantity=0,
        sub_attributes={},
    )
    assert status_zero == StockStatus.CRITICAL
    assert restock_zero is True


@pytest.mark.asyncio
async def test_edited_protocol_message_embalagens_and_sorvetes(api_client: AsyncClient):
    # Primeiro cadastra Mercado (com biscoito Oreo) para garantir que Sorvete Oreo não conflite
    mercado_payload = {
        "event": "messages.upsert",
        "instance": "vitinho",
        "data": {
            "key": {"remoteJid": "557188908550-1544726594@g.us"},
            "message": {"conversation": REAL_RESTAURANT_MESSAGES[2][1]},
        },
    }
    r_merc = await api_client.post("/api/v1/webhook/evolution", json=mercado_payload)
    assert r_merc.status_code == 200

    # Simula mensagem EDITADA no WhatsApp (protocolMessage.editedMessage) com Embalagens + *SORVETES + *Batata frita
    edited_embalagens_payload = {
        "event": "messages.update",
        "instance": "vitinho",
        "data": {
            "key": {"remoteJid": "557188908550-1544726594@g.us"},
            "message": {
                "protocolMessage": {
                    "type": "MESSAGE_EDIT",
                    "editedMessage": {
                        "conversation": REAL_RESTAURANT_MESSAGES[5][1],
                    },
                }
            },
        },
    }
    r_edit = await api_client.post("/api/v1/webhook/evolution", json=edited_embalagens_payload)
    assert r_edit.status_code == 200
    body = r_edit.json()
    assert body["status"] == "processed"
    assert "Embalagens e Preparos" in body["affected_sections"]
    assert "Sorvetes" in body["affected_sections"]

    dash_resp = await api_client.get("/api/v1/dashboard")
    assert dash_resp.status_code == 200
    sections = {s["health"]["name"]: s["products"] for s in dash_resp.json()["sections"]}

    emb_names = {p["canonical_name"] for p in sections["Embalagens e Preparos"]}
    sorv_names = {p["canonical_name"] for p in sections["Sorvetes"]}
    merc_names = {p["canonical_name"] for p in sections["Mercado"]}

    assert "Caixa Quadrada Grande" in emb_names
    assert "Massas Boleadas" in emb_names
    assert "Batata Frita" in emb_names
    assert "Batata Frita" not in sorv_names
    assert {"Ovomaltine", "Paçoca", "Oreo"}.issubset(sorv_names)
    assert "Oreo" in merc_names


@pytest.mark.asyncio
async def test_pizzaria_and_diparma_unification_without_duplicates_or_data_loss(db_session: AsyncSession):
    stock_service = StockService(db_session)
    prod_repo = ProductRepository(db_session)

    # 1. Processa Açougue, Frios e Mercado da Pizzaria (note que Frango aparece tanto em Frios quanto em Açougue!)
    await stock_service.process_whatsapp_message(raw_message=REAL_RESTAURANT_MESSAGES[1][1], replace_section_snapshot=True)
    await stock_service.process_whatsapp_message(raw_message=REAL_RESTAURANT_MESSAGES[0][1], replace_section_snapshot=True)
    await stock_service.process_whatsapp_message(raw_message=REAL_RESTAURANT_MESSAGES[2][1], replace_section_snapshot=True)

    # 2. Processa RELAÇÃO PRODUTOS DIPARMA (Comida Italiana)
    diparma_msg = """RELAÇÃO PRODUTOS DIPARMA

▶️ FRANGO
15KILOS
20 PORÇÕES

▶️ CAMARÃO
04KILOS
12 PORÇÕES

▶️ FILE MIGNON
02 PEÇAS
14 PORÇÕES

▶️ FETTUCCINE
14FECHADAS
00 CAIXAS FECHADAS

▶️ OLEO SOJA
08 UNIDADES

▶️ ACUCAR
04KILOS

▶️ MOLHO SUGO
04 VASILHAS

▶️ BROCOLIS
O0PACOTE
10 PORÇÕES"""
    await stock_service.process_whatsapp_message(raw_message=diparma_msg, replace_section_snapshot=True)

    all_prods = await prod_repo.list_all()
    by_norm: dict[str, list[Product]] = {}
    for p in all_prods:
        by_norm.setdefault(p.normalized_name, []).append(p)

    # Zero duplicatas para itens compartilhados entre Frios, Açougue, Mercado e DiParma!
    for shared_key in ("frango", "camarao", "oleo", "acucar", "molho sugo", "brocolis"):
        assert len(by_norm[shared_key]) == 1, f"Produto duplicado detectado: {shared_key}"

    # Frango deve preservar tanto as porções da Pizzaria quanto os cortes do DiParma
    frango = by_norm["frango"][0]
    assert frango.category.name == "Açougue"
    assert "porcoes" in frango.sub_attributes
    assert "porcoes_diparma" in frango.sub_attributes

    # Fettuccine com 14FECHADAS + 00 CAIXAS FECHADAS deve usar o saldo positivo (14 fechadas -> OK)
    fettuccine = by_norm["fettuccine"][0]
    assert fettuccine.stock_status == StockStatus.OK

    # Brócolis com O0PACOTE (typo O0 -> 00) + 10 PORÇÕES -> PORTIONED (Azul)
    brocolis = by_norm["brocolis"][0]
    assert brocolis.stock_status == StockStatus.PORTIONED

    # 3. Reenviar relatório de Açougue da Pizzaria NÃO pode apagar Filé Mignon exclusivo do DiParma!
    await stock_service.process_whatsapp_message(raw_message=REAL_RESTAURANT_MESSAGES[0][1], replace_section_snapshot=True)
    after_prods = {p.normalized_name: p for p in await prod_repo.list_all()}
    assert "file mignon" in after_prods
    assert "fettuccine" in after_prods


@pytest.mark.asyncio
async def test_loose_non_standard_message_updates_existing_only_never_creates(db_session: AsyncSession):
    stock_service = StockService(db_session)
    prod_repo = ProductRepository(db_session)

    # Cadastra Hortifrutis pelo padrão oficial (contém Limão e Morango Suco)
    await stock_service.process_whatsapp_message(raw_message=REAL_RESTAURANT_MESSAGES[3][1], replace_section_snapshot=True)
    initial_count = len(await prod_repo.list_all())

    # Envia mensagem fora do padrão oficial misturando item existente ("Limão: 05 pacotes") e item inédito ("Trufa Negra Importada: 03")
    loose_msg = """Limão: 05 sacos
Trufa Negra Importada: 03 kg"""
    res = await stock_service.process_whatsapp_message(raw_message=loose_msg, replace_section_snapshot=True)

    assert res.status == "processed"
    assert res.created_products_count == 0
    assert res.updated_products_count == 1

    final_prods = {p.normalized_name: p for p in await prod_repo.list_all()}
    assert len(final_prods) == initial_count
    assert "trufa negra importada" not in final_prods
    assert final_prods["limao"].raw_main_value == "05 sacos"
    assert final_prods["limao"].stock_status == StockStatus.OK
