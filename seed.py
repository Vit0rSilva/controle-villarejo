"""
Script de Inicialização com os relatórios reais atuais do grupo 557188908550-1544726594@g.us.
Não mistura dados fictícios: limpa e aplica exatamente as mensagens atuais de cada seção.
Execução:
    python3 seed.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from app.core import database
from app.core.config import settings
from app.models.product import Product
from app.models.stock_log import StockLog
from app.repositories.category_repository import CategoryRepository
from app.services.stock_service import StockService


REAL_RESTAURANT_MESSAGES: list[tuple[str, str, int]] = [
    (
        "Mensagem Atual - Açougue",
        """AÇOUGUE
● Carne do Sol : 00 🥩
• 00 Porções de 100g
• 13 Porções de petisco 300
Cozida: 00
● Carne Seca: 00
33 porções de 100g
● Costelinha: 00🍖
09 porções de 100g
• Cozida: 00
● Frango 7kg 🐔
• 34 Porções de 100
Cozido: 01 panela em produção
● Camarão:🦐 7kg
porções: Tem
● Salmão:
01 peça: 🐠
03 Porções 150g
01 Porções 100g""",
        1,
    ),
    (
        "Mensagem Atual - Frios",
        """Frios
Atum: 3,500kg
Aberto: 00
Bacon: 00
Porções: 35 de 100g
Barbecue: 01 fechado
Aberto: 01
Calabresa fatiada: 00
Porções: 65 de 100g
Calabresa ralada: 03 de 100g
Farinha de trigo: 30kg
Frango : 2kg
Porções: 30 de 100g
Cozido: 00
Gorgonzola: 00 barrinhas
Porções: 25 porções de 50g
Granulado: 1kg
Aberto: 01
Leite condensado: 06 uni
Lombinho:
Porções: 27 de 100
Mussarela: 03 barras
1 vasilha
Mussarela zero lactose: 04 barrinhas
Peito de peru: 00
Porções: 13 de 100g
Pepperoni: 1kg
Porções 28 Porções de 80g
Presunto: 00
Porções: 10 Porções de 100g
Provolone: 02
Porções: 05 de 50g
Ralado: 00
Queijo coalho: tem
Porções: 52 de 50g
Requeijão Catupiry: 02 unidade
Requeijão Tirolez: 08 uni
Aberto : 01
Creme cheese: 01
Aberto: 00
Requeijão Cheddar: 02
Aberto: 01""",
        2,
    ),
    (
        "Mensagem Atual - Mercado",
        """Mercado
Açúcar: tem
Aberto: 1
Açúcar demerara: 1kg
Azeite doce: 00
Aberto: 01
Azeitona: 02
Aberto: 01
Alho frito: tem
Brócolis 🥦: 3
Congelado: pouco
Canela em pó: Tem
Chocolate de Avelã: 01
Aberto: 01
Doritos: 01
Aberto: 00
Creme de leite: 14 uni
Creme culinário: 00
Leite em pó: 1 lata
Aberto: Tem
Nescau: 2kg
Aberto: tem
Oreo: 4 uni
Orégano: Tem
Ovo de codorna: 5
Cozida: pouca
Bobina: 00
Em uso: 00 trazer
Milho: tem
Molho Tarê: 10L
Óleo: tem
Molho Sugo: 3 vasilhas
00 Panelas pronta
00 panela em produção
Pimenta calabresa: Tem
Goiabada: 02
Aberto : 1
Sal: Tem
Corante: Tem
Fermento: 02
Aberto: 01
M&M: 02
Aberto: 01
Fuba: Tem
Saco de cachorro quente: tem
Vinagre: Tem
Pão de hot dog: 00
Salsicha: Tem
Cuscuz :03 unidade
Batata palha:02 fechado
Aberto: 01""",
        3,
    ),
    (
        "Mensagem Atual - Hortifrutis",
        """Hortifrutis
•Abacaxi 🍍05 unidade
Cortado: 01
•Banana da prata: 03
•Banana da Terra
04 Vasilhas de purê
Pencas: 00
•Cebola grande 🧅 trazer
•Tomate grande 🍅 tem
Tomate Cereja 🍒 tem
Tomate Seco: 01 balde
aberto: 01
Palmito:
Fechado: 01
Aberto: 00
Para Suco 🧋
Maracujá 🍑 1 Pct e Meio
150 porção: 00
100 porca : 00
Laranja 🍊 temm
Morango Suco🍓 1,500kg
Morango pizza: Trazer
Limão 🍋 00
FOLHAS
Manjericão🍃 1 pé
Rúcula 🥗 1 pé
Coentro: trazer
Pimentão 🫑 1
Cebolinha: pouca
Alface roxo para salada: tem
Alface verde: tem
Gergelim preto: tem
Gergelim branco: Tem""",
        1,
    ),
    (
        "Mensagem Atual - Produtos de Limpeza",
        """Produtos de limpeza
Cifff: 02
Aberto: 01
Detergente: 08
Sabão em pó: 02
Aberto: 01
Água sanitária: 04
Desinfetante: 02
Papel toalha: 03 fardos
Saco de lixo 100L: 02
Saco de lixo 50L: 00
Aberto: Pouco
Esponja: 05
Bombril: Tem
Touca: 01 pacote""",
        2,
    ),
    (
        "Mensagem Atual - Embalagens, Preparos e Sorvetes",
        """Caixa quadrada grande: 85
Caixa quadrada pequena: 40
Caixa super fatia: 30
Massas boleadas: 45
Massas abertas: 12
Molho e queijo: 02 vasilhas
Brigadeiro de panela: 01 vasilha
Brigadeiro de leite ninho: 00

*SORVETES:
Ovomaltine: 01 balde
Paçoca: 00
Oreo: Pouco
*Batata frita: 02 pacotes""",
        1,
    ),
    (
        "Mensagem Atual - Relação Produtos DiParma",
        """RELAÇÃO PRODUTOS DIPARMA

▶️ FRANGO
07KILOS
20 PORÇÕES

▶️ CAMARÃO
07KILOS
12 PORÇÕES

▶️ FILE MIGNON
02 PEÇAS
14 PORÇÕES

▶️ FETTUCCINE
14FECHADAS
00 CAIXAS FECHADAS

▶️ PENNE
05 PACOTES

▶️ LASANHA
08 PORÇÕES

▶️ OLEO SOJA
08 UNIDADES

▶️ MOLHO SUGO
03 VASILHAS""",
        2,
    ),
]


async def run_seed(clear_existing: bool = True) -> None:
    active_url = await database.ensure_database_ready()
    print(f"📦 Conectado ao banco de dados: {active_url}")

    async with database.AsyncSessionLocal() as session:
        cat_repo = CategoryRepository(session)
        stock_service = StockService(session)

        if clear_existing:
            await session.execute(
                delete(Product),
                execution_options={"synchronize_session": False},
            )
            await session.execute(
                delete(StockLog),
                execution_options={"synchronize_session": False},
            )
            from app.models.category import Category

            await session.execute(
                update(Category).values(last_updated_at=None, last_update_source=None),
                execution_options={"synchronize_session": False},
            )
            await session.commit()
            session.expunge_all()

        await cat_repo.ensure_default_categories()

        now = datetime.now(timezone.utc)
        print(f"\n🚀 Carregando os {len(REAL_RESTAURANT_MESSAGES)} relatórios atuais do grupo {settings.TARGET_GROUP_JID}...\n")

        for title, raw_msg, hours_ago in REAL_RESTAURANT_MESSAGES:
            ref_time = now - timedelta(hours=hours_ago)
            res = await stock_service.process_whatsapp_message(
                raw_message=raw_msg,
                instance_name=settings.EVOLUTION_INSTANCE_NAME,
                sender_phone=settings.TARGET_GROUP_JID,
                source="WHATSAPP",
                reference_timestamp=ref_time,
                replace_section_snapshot=True,
                group_jid=settings.TARGET_GROUP_JID,
            )
            print(
                f"  ✅ {title}\n"
                f"     • Seções: {', '.join(res.affected_sections)}\n"
                f"     • Itens atuais: {res.parsed_items_count} "
                f"(Críticos: {res.critical_items_count}, Atenção: {res.warning_items_count})"
            )

        dashboard = await stock_service.get_dashboard_data()
        print("\n" + "=" * 72)
        print("📊 RESUMO DO PAINEL (SOMENTE MENSAGENS ATUAIS)")
        print("=" * 72)
        print(f"Grupo Monitorado  : {settings.TARGET_GROUP_JID}")
        print(f"Total de Seções   : {dashboard.stats.total_sections} ({dashboard.stats.stale_sections_count} sem envio nas últimas 24h)")
        print(f"Total de Produtos : {dashboard.stats.total_products}")
        print(f"  🚨 CRITICAL     : {dashboard.stats.critical_products_count}")
        print(f"  ⚠️ WARNING      : {dashboard.stats.warning_products_count}")
        print(f"  🧊 PORTIONED    : {dashboard.stats.portioned_products_count}")
        print(f"  ✅ OK           : {dashboard.stats.ok_products_count}")
        print("=" * 72)


if __name__ == "__main__":
    asyncio.run(run_seed(clear_existing=True))
