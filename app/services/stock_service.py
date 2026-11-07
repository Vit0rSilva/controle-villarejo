from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import EntityNotFoundError
from app.models.category import Category
from app.models.product import Product, StockStatus
from app.repositories.category_repository import CategoryRepository
from app.repositories.log_repository import LogRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.category import CategoryHealthResponse
from app.schemas.dashboard import (
    DashboardResponse,
    DashboardSectionWithProducts,
    DashboardStats,
    MissingProductSummaryItem,
)
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from app.schemas.webhook import ParseResultResponse
from app.services.fuzzy_service import FuzzyService
from app.services.parser_service import ParsedProductItem, ParserService


# Mapeamento canônico de seção para impedir duplicidade entre relatórios (ex: Frios vs Açougue vs DiParma)
CANONICAL_PRODUCT_SECTION: dict[str, str] = {
    # Açougue / Proteínas (unifica Frios + Açougue + DiParma)
    "frango": "Açougue",
    "camarao": "Açougue",
    "salmao": "Açougue",
    "file mignon": "Açougue",
    "carne moida": "Açougue",
    "carne do sol": "Açougue",
    "carne seca": "Açougue",
    "costelinha": "Açougue",
    # Embalagens e Preparos (Pizzaria + DiParma, incluindo itens pós-*SORVETES como *Batata frita)
    "caixa quadrada grande": "Embalagens e Preparos",
    "caixa quadrada pequena": "Embalagens e Preparos",
    "caixa super fatia": "Embalagens e Preparos",
    "massas boleadas": "Embalagens e Preparos",
    "massas abertas": "Embalagens e Preparos",
    "molho e queijo": "Embalagens e Preparos",
    "brigadeiro de panela": "Embalagens e Preparos",
    "brigadeiro de leite ninho": "Embalagens e Preparos",
    "batata frita": "Embalagens e Preparos",
    "sacolas": "Embalagens e Preparos",
    "quentinha": "Embalagens e Preparos",
    "quentinha de plastico": "Embalagens e Preparos",
    "vasilhas de porcoes extra": "Embalagens e Preparos",
    "kit de talher": "Embalagens e Preparos",
    "garrafa de suco": "Embalagens e Preparos",
    # Frios (Pizzaria + DiParma)
    "parmesao": "Frios",
    "bacon fatiado": "Frios",
    "bacon": "Frios",
    "margarina": "Frios",
    # Hortifrutis (Pizzaria + DiParma)
    "alho": "Hortifrutis",
    "batata": "Hortifrutis",
    "alface verde": "Hortifrutis",
    "alface roxo para salada": "Hortifrutis",
    # Mercado (unifica Pizzaria + DiParma)
    "oleo": "Mercado",
    "acucar": "Mercado",
    "molho sugo": "Mercado",
    "molho branco": "Mercado",
    "brocolis": "Mercado",
    "batata palha": "Mercado",
    "leite liquido": "Mercado",
    "fettuccine": "Mercado",
    "penne": "Mercado",
    "espaguete": "Mercado",
    "nhoque": "Mercado",
    "lasanha": "Mercado",
    "farinha de rosca": "Mercado",
    "knorr de frango": "Mercado",
    "knorr de carne": "Mercado",
    "ovos": "Mercado",
    "arroz risoto": "Mercado",
    "arroz com brocolis": "Mercado",
    "mel": "Mercado",
    "pimenta biquinho": "Mercado",
    "mostarda": "Mercado",
}

# Heurística de palavras-chave no nome do produto quando ainda não existe no banco
SECTION_INFERENCE_KEYWORDS: dict[str, list[str]] = {
    "Embalagens e Preparos": [
        "caixa",
        "caixas",
        "oitavada",
        "quadrada",
        "massa",
        "massas",
        "boleada",
        "boleadas",
        "embalagem",
        "embalagens",
        "sacola",
        "sacolas",
        "quentinha",
        "talher",
        "brigadeiro",
        "lacre",
        "isopor",
        "preparo",
    ],
    "Produtos de Limpeza": [
        "cif",
        "detergente",
        "sabao",
        "agua sanitaria",
        "quiboa",
        "qboa",
        "desinfetante",
        "cheirinho",
        "vassoura",
        "touca",
        "veja",
        "multiuso",
        "esponja",
        "bucha",
        "bombril",
        "papel toalha",
        "papel higienico",
        "saco de lixo",
        "alcool",
        "limpa aluminio",
        "pano",
        "luva",
    ],
    "Sorvetes": [
        "sorvete",
        "sorvetes",
        "picole",
        "acai",
        "napolitano",
        "flocos",
    ],
    "Frios": [
        "mussarela",
        "queijo",
        "presunto",
        "calabresa",
        "bacon",
        "catupiry",
        "requeijao",
        "cream cheese",
        "cheddar",
        "gorgonzola",
        "parmesao",
        "coalho",
        "lombinho",
        "peito de peru",
        "pepperoni",
        "provolone",
        "atum",
        "barbecue",
        "granulado",
        "salame",
        "manteiga",
        "margarina",
        "chantilly",
    ],
    "Açougue": [
        "carne",
        "frango",
        "file",
        "camarao",
        "salmao",
        "peixe",
        "costela",
        "costelinha",
        "picanha",
        "alcatra",
        "moida",
        "hamburguer",
        "linguica",
        "charque",
        "cupim",
        "contra file",
    ],
    "Hortifrutis": [
        "tomate",
        "cebola",
        "alho",
        "batata",
        "alface",
        "rucula",
        "manjericao",
        "coentro",
        "cebolinha",
        "pimentao",
        "limao",
        "laranja",
        "abacaxi",
        "morango",
        "maracuja",
        "acerola",
        "manga",
        "goiaba",
        "banana",
        "palmito",
        "gergelim",
        "cenoura",
        "macaxeira",
        "aipim",
        "hortela",
        "repolho",
    ],
    "Mercado": [
        "arroz",
        "feijao",
        "macarrao",
        "espaguete",
        "fettuccine",
        "penne",
        "nhoque",
        "lasanha",
        "oleo",
        "azeite",
        "farinha",
        "trigo",
        "acucar",
        "sal",
        "leite",
        "molho",
        "extrato",
        "ketchup",
        "maionese",
        "mostarda",
        "milho",
        "ervilha",
        "azeitona",
        "oregano",
        "chocolate",
        "creme de leite",
        "creme culinario",
        "leite condensado",
        "nescau",
        "oreo",
        "doritos",
        "brocolis",
        "canela",
        "bobina",
        "goiabada",
        "fermento",
        "fuba",
        "vinagre",
        "salsicha",
        "cuscuz",
        "batata palha",
        "knorr",
        "mel",
        "ovos",
    ],
}


class StockService:
    """Serviço de domínio responsável pelo controle de estoque, regras anti-duplicidade e consolidação do painel."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.category_repo = CategoryRepository(session)
        self.product_repo = ProductRepository(session)
        self.log_repo = LogRepository(session)

    @classmethod
    def _is_sub_value_positive(cls, val: str) -> bool:
        """
        Determina se o texto de um sub-atributo (ex: '35 de 100g', 'Sim', '01', 'Pouco', '00')
        indica existência real de estoque secundário (> 0).
        """
        if not val:
            return False
        if "|" in val:
            return any(cls._is_sub_value_positive(part.strip()) for part in val.split("|"))

        norm = FuzzyService.remove_accents(val.lower()).strip()
        if norm in ("0", "00", "000", "nada", "acabou", "falta", "zerado", "nao tem", "nao", "sem", "fazer", "trazer"):
            return False

        m = re.match(r"^(\d+(?:[.,]\d+)?)", norm)
        if m:
            try:
                num = float(m.group(1).replace(",", "."))
                return num > 0
            except ValueError:
                pass

        numbers = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", norm)]
        if numbers:
            return any(n > 0 for n in numbers)

        if any(w in norm for w in ("tem", "sim", "pouco", "pouca", "meia", "meio", "em uso", "abert", "producao")):
            return True

        return False

    @classmethod
    def _extract_leading_count(cls, text: str) -> float:
        """
        Extrai a quantidade principal no início de uma descrição de porção/vasilha
        (ex: '35 de 100g' -> 35.0, '00 Porções de 100g' -> 0.0, 'Porções 20 Porções de 80g' -> 20.0, 'Tem' -> 10.0).
        """
        if not text:
            return 0.0
        norm = FuzzyService.remove_accents(text.lower()).strip()
        # Remove prefixo 'porcoes' caso esteja no início ("Porções 20 Porções de 80g")
        norm_stripped = re.sub(r"^por[cç](?:oes|ao|a)?\s*[:\-]?\s*", "", norm).strip()
        m = re.match(r"^(\d+(?:[.,]\d+)?)", norm_stripped)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                return 0.0
        if re.search(r"\b(?:tem|sim|bastante)\b", norm) and "pouc" not in norm:
            return 10.0
        if re.search(r"\b(?:pouc[oa]|meia|meio)\b", norm):
            return 1.0
        return 0.0

    @classmethod
    def _extract_available_sub_summary(cls, sub_attributes: dict[str, Any]) -> list[str]:
        """Retorna lista descritiva dos sub-itens que possuem saldo disponível (> 0)."""
        available: list[str] = []
        if not sub_attributes:
            return available

        for p_key, prefix in (("porcoes", ""), ("porcoes_diparma", "DiParma: ")):
            porcoes = sub_attributes.get(p_key)
            if isinstance(porcoes, list):
                for p in porcoes:
                    if isinstance(p, str) and cls._is_sub_value_positive(p):
                        if any(
                            w in FuzzyService.remove_accents(p.lower())
                            for w in ("porc", "parmegiana", "escalope", "medalhao", "file", "pure")
                        ):
                            available.append(f"{prefix}{p}")
                        else:
                            available.append(f"{prefix}{p} porções")
            elif isinstance(porcoes, str) and cls._is_sub_value_positive(porcoes):
                available.append(f"{prefix}{porcoes}")

        for key, label in (
            ("aberto", "Aberto"),
            ("fechado", "Fechado"),
            ("em_uso", "Em uso"),
            ("cozido", "Cozido"),
            ("congelado", "Congelado"),
            ("ralado", "Ralado"),
            ("cortado", "Cortado"),
            ("panelas", "Panelas"),
            ("vasilhas", "Vasilhas"),
            ("pencas", "Pencas"),
        ):
            val = sub_attributes.get(key)
            if isinstance(val, str) and cls._is_sub_value_positive(val):
                if label.lower() in FuzzyService.remove_accents(val.lower()):
                    available.append(val)
                else:
                    available.append(f"{label}: {val}")

        return available

    @classmethod
    def evaluate_stock_status(
        cls,
        raw_main_value: str,
        numeric_quantity: Decimal | float | None,
        sub_attributes: dict[str, Any] | None = None,
        is_incomplete_data: bool = False,
    ) -> tuple[StockStatus, bool, str | None]:
        """
        Regras de classificação do estoque:
        1. `CRITICAL` (Vermelho / Em Falta): Zerado total (`00` sem porções/abertos) ou marcado com `Trazer` / `Acabou` / `Falta`.
        2. `PORTIONED` (Azul / Só Porção): Unidade fechada zerada (`00`), sem palavra `"pouco"`, mas com BASTANTE porção pronta (`>= PLENTY_PORTIONS_THRESHOLD` ou `>= 2` vasilhas prontas). Não é falta nem pouco!
        3. `WARNING` (Amarelo / Pouco): Frase com `"pouco"` / `"meia"` / `"abaixo de"`, ou fechado zerado restando quantidade bem pequena de porções (`1..5`) / apenas 1 pacote aberto.
        4. `OK` (Verde / Em Dia): Unidades fechadas / quilos / `Tem` disponíveis normalmente.
        """
        subs = sub_attributes or {}
        norm_main = FuzzyService.remove_accents((raw_main_value or "").lower()).strip()
        available_subs = cls._extract_available_sub_summary(subs)

        # Soma total de porções disponíveis (Pizzaria + DiParma)
        total_portions = 0.0
        for p_key in ("porcoes", "porcoes_diparma"):
            p_val = subs.get(p_key)
            if isinstance(p_val, list):
                for entry in p_val:
                    if isinstance(entry, str) and cls._is_sub_value_positive(entry):
                        total_portions += cls._extract_leading_count(entry)
            elif isinstance(p_val, str) and cls._is_sub_value_positive(p_val):
                total_portions += cls._extract_leading_count(p_val)

        prepared_vasilhas = 0.0
        for c_key in ("vasilhas", "panelas"):
            c_val = subs.get(c_key)
            if isinstance(c_val, str) and cls._is_sub_value_positive(c_val):
                for part in c_val.split("|"):
                    prepared_vasilhas += cls._extract_leading_count(part)

        subs_text_norm = FuzzyService.remove_accents(
            " ".join(str(v) for k, v in subs.items() if k not in ("subcategoria", "origens")).lower()
        )
        has_pouco_in_subs = bool(re.search(r"\bpouc[oa]s?\b|\bacabando\b|\bfinal\b", subs_text_norm))

        # 1. Termos críticos explícitos no valor principal ("trazer", "acabou", "falta", "comprar")
        critical_keywords = ("trazer", "fazer", "acabou", "falta", "comprar", "zerado", "sem estoque")
        if any(re.search(rf"\b{kw}\b", norm_main) for kw in critical_keywords):
            if available_subs:
                note = f"Reposição solicitada ({raw_main_value}) • Restam: {', '.join(available_subs)}"
            else:
                note = f"Reposição urgente ({raw_main_value or 'Em falta'})"
            return StockStatus.CRITICAL, True, note

        # 2. Verifica se o valor principal (fechado/bruto) é zero ("00", "0", numeric_quantity == 0) ou vazio
        main_is_zero = False
        if norm_main in ("0", "00", "000"):
            main_is_zero = True
        elif numeric_quantity is not None and float(numeric_quantity) == 0.0 and "+" not in norm_main:
            if not re.search(r"\b(?:tem|sim)\b", norm_main):
                main_is_zero = True

        if main_is_zero or not norm_main:
            if not available_subs:
                if not norm_main and is_incomplete_data:
                    return (
                        StockStatus.NEEDS_ACTION,
                        True,
                        "Dado incompleto na mensagem do WhatsApp",
                    )
                return (
                    StockStatus.CRITICAL,
                    True,
                    "Estoque zerado (Sem unidades fechadas nem porções)",
                )

            joined_subs = ", ".join(available_subs)
            sub_action = str(subs.get("acao") or "").lower()
            if sub_action in ("trazer", "comprar", "fazer", "precisa"):
                return (
                    StockStatus.CRITICAL,
                    True,
                    f"Solicitado reposição • Em uso/porção: {joined_subs}",
                )

            # Se houver "pouco" explícito nos sub-itens -> Amarelo (Pouco)
            if has_pouco_in_subs:
                return (
                    StockStatus.WARNING,
                    True,
                    f"Pouco estoque restante ({joined_subs})",
                )

            # Se tem BASTANTE porção (>= 6 porções ou >= 2 vasilhas de preparo) -> AZUL (PORTIONED)
            if total_portions >= settings.PLENTY_PORTIONS_THRESHOLD or prepared_vasilhas >= 2.0:
                return (
                    StockStatus.PORTIONED,
                    False,
                    f"Só porção / preparo com bom saldo ({joined_subs})",
                )

            # Caso contrário, valor bem pequeno de porções (1 a 5) ou apenas último aberto -> Amarelo (Pouco)
            return (
                StockStatus.WARNING,
                True,
                f"Pouco: fechado zerado, restam apenas {joined_subs}",
            )

        # 3. Valor principal > 0 ou "Tem": verifica indicadores explícitos de "pouco"
        warning_patterns = (
            r"\bpouc[oa]s?\b",
            r"\babaixo\s+de\b",
            r"\bmei[oa]\b",
            r"\b1/2\b",
            r"\bacabando\b",
            r"\bfinal\b",
            r"\brest[ao]m?\s+pouc",
            r"\bprecisa\b",
        )
        # "3 Pct e Meio" ou "01 e Meia" têm quantidade >= 1.5, logo NÃO são meia unidade!
        is_more_than_one_and_half = bool(
            re.search(r"\b[1-9]\d*\s*(?:[a-z]+\s+)?e\s+mei[oa]\b", norm_main)
        )
        if not is_more_than_one_and_half and any(re.search(pat, norm_main) for pat in warning_patterns):
            return (
                StockStatus.WARNING,
                True,
                f"Estoque baixo ({raw_main_value})",
            )

        # Se o próprio valor principal for medido apenas em porções pequenas (ex: "03 de 100g") e <= 5
        has_closed_package_unit = bool(
            re.search(
                r"\b(?:pacotes?|pcts?|sacos?|fardos?|caixas?|latas?|baldes?|potes?|garrafas?|barras?|pe[cç]as?|unidades?|uni)\b",
                norm_main,
            )
        )
        if (
            numeric_quantity is not None
            and 0 < float(numeric_quantity) < settings.PLENTY_PORTIONS_THRESHOLD
            and not has_closed_package_unit
            and re.search(r"\bde\s+\d+\s*g\b|\bpor[cç]", norm_main)
        ):
            return (
                StockStatus.WARNING,
                True,
                f"Poucas porções ({raw_main_value})",
            )

        sub_action = str(subs.get("acao") or "").lower()
        if sub_action in ("fazer", "trazer", "comprar", "precisa"):
            return (
                StockStatus.WARNING,
                True,
                f"Atenção: marcado para reposição ({raw_main_value})",
            )

        note = "Revisar dado incompleto" if is_incomplete_data else None
        return StockStatus.OK, False, note

    @staticmethod
    def compute_category_health(
        category: Category,
        now: datetime | None = None,
    ) -> CategoryHealthResponse:
        """Calcula o status de atualização (regra de 24 horas) e contadores de alerta de uma seção."""
        ref_now = now or datetime.now(timezone.utc)
        threshold_hours = settings.STALE_SECTION_HOURS

        last_up = category.last_updated_at
        if last_up is not None and last_up.tzinfo is None:
            last_up = last_up.replace(tzinfo=timezone.utc)

        hours_since: float | None = None
        is_stale = True
        human_time = "Nunca atualizado"

        if last_up is not None:
            delta_seconds = max(0.0, (ref_now - last_up).total_seconds())
            hours_since = round(delta_seconds / 3600.0, 1)
            is_stale = hours_since > threshold_hours

            if delta_seconds < 60:
                human_time = "Agora mesmo"
            elif delta_seconds < 3600:
                mins = int(delta_seconds // 60)
                human_time = f"Há {mins} min"
            elif hours_since < 24:
                hrs = int(hours_since)
                human_time = f"Há {hrs} hora{'s' if hrs != 1 else ''}"
            else:
                days = int(hours_since // 24)
                rem_hours = int(hours_since % 24)
                if rem_hours > 0:
                    human_time = f"Há {days}d {rem_hours}h ({int(hours_since)}h)"
                else:
                    human_time = f"Há {days} dia{'s' if days != 1 else ''} ({int(hours_since)}h)"

        stale_msg: str | None = None
        if is_stale:
            stale_msg = (
                f"⚠️ Atenção: A seção {category.name} está há mais de {threshold_hours} horas "
                f"sem atualização! Verifique se a contagem foi enviada no WhatsApp."
            )

        products = category.products or []
        critical_count = sum(1 for p in products if p.stock_status == StockStatus.CRITICAL)
        warning_count = sum(
            1 for p in products if p.stock_status in (StockStatus.WARNING, StockStatus.NEEDS_ACTION)
        )
        portioned_count = sum(1 for p in products if p.stock_status == StockStatus.PORTIONED)
        incomplete_count = sum(1 for p in products if p.is_incomplete_data)

        return CategoryHealthResponse(
            id=category.id,
            name=category.name,
            slug=category.slug,
            display_order=category.display_order,
            last_updated_at=last_up,
            last_update_source=category.last_update_source,
            hours_since_update=hours_since,
            human_time_since_update=human_time,
            is_stale=is_stale,
            stale_alert_message=stale_msg,
            total_products=len(products),
            critical_count=critical_count,
            warning_count=warning_count,
            portioned_count=portioned_count,
            incomplete_count=incomplete_count,
            alert_items_count=critical_count + warning_count,
        )

    @classmethod
    def to_product_response(cls, product: Product, category_name: str | None = None) -> ProductResponse:
        _, _, status_note = cls.evaluate_stock_status(
            raw_main_value=product.raw_main_value,
            numeric_quantity=product.numeric_quantity,
            sub_attributes=product.sub_attributes,
            is_incomplete_data=product.is_incomplete_data,
        )
        cat_name = category_name or (product.category.name if product.category else None)
        return ProductResponse(
            id=product.id,
            category_id=product.category_id,
            category_name=cat_name,
            canonical_name=product.canonical_name,
            normalized_name=product.normalized_name,
            aliases=list(product.aliases or []),
            raw_main_value=product.raw_main_value,
            numeric_quantity=float(product.numeric_quantity) if product.numeric_quantity is not None else None,
            unit=product.unit,
            sub_attributes=dict(product.sub_attributes or {}),
            stock_status=product.stock_status,
            needs_restock=product.needs_restock,
            is_incomplete_data=product.is_incomplete_data,
            status_note=status_note,
            updated_at=product.updated_at,
        )

    def _infer_section_for_item(
        self,
        item: ParsedProductItem,
        all_products: list[Product],
        categories_by_name: dict[str, Category],
    ) -> str | None:
        if item.normalized_name in CANONICAL_PRODUCT_SECTION:
            return CANONICAL_PRODUCT_SECTION[item.normalized_name]

        non_sorvete_products = [
            p for p in all_products if p.category is None or p.category.name != "Sorvetes"
        ]
        matched_prod, _ = FuzzyService.find_best_product_match(item.raw_name, non_sorvete_products)
        if matched_prod is not None and matched_prod.category is not None:
            return matched_prod.category.name

        norm = item.normalized_name
        for sec_name, kw_list in SECTION_INFERENCE_KEYWORDS.items():
            if sec_name in categories_by_name:
                for kw in kw_list:
                    if re.search(rf"\b{re.escape(kw)}\b", norm):
                        return sec_name
        return None

    @staticmethod
    def _merge_sub_attributes(
        existing_subs: dict[str, Any] | None,
        incoming_subs: dict[str, Any] | None,
        report_origin: str,
    ) -> dict[str, Any]:
        """
        Mescla sub-atributos sem misturar dados antigos da mesma cozinha, mas preservando
        cortes exclusivos entre Pizzaria (`porcoes`) e DiParma (`porcoes_diparma`).
        """
        prev = dict(existing_subs or {})
        inc = dict(incoming_subs or {})
        merged: dict[str, Any] = {}

        # Preserva origens conhecidas
        prev_origins = list(prev.get("origens") or [])
        if report_origin in ("PIZZARIA", "DIPARMA") and report_origin not in prev_origins:
            prev_origins.append(report_origin)
        if prev_origins:
            merged["origens"] = prev_origins

        if report_origin == "DIPARMA":
            # Mantém porções da Pizzaria e subcategoria se já existiam, atualizando cortes do DiParma
            if "porcoes" in prev:
                merged["porcoes"] = prev["porcoes"]
            if "subcategoria" in prev and "subcategoria" not in inc:
                merged["subcategoria"] = prev["subcategoria"]
            for k, v in inc.items():
                if k != "origens":
                    merged[k] = v
        elif report_origin == "PIZZARIA":
            # Mantém cortes do DiParma se já existiam, atualizando todos os dados da Pizzaria
            if "porcoes_diparma" in prev:
                merged["porcoes_diparma"] = prev["porcoes_diparma"]
            for k, v in inc.items():
                if k != "origens":
                    merged[k] = v
        else:
            # Atualização pontual (LOOSE): preserva sub-atributos anteriores caso a mensagem só tenha mudado o principal
            merged.update(prev)
            for k, v in inc.items():
                if k != "origens":
                    merged[k] = v
            if prev_origins:
                merged["origens"] = prev_origins

        return merged

    async def deduplicate_existing_products(self) -> int:
        """
        Varre o banco consolidando eventuais duplicatas históricas (ex: 'Frango' em Frios e Açougue,
        'Óleo' e 'Oleo Soja'), mantendo apenas 1 registro canônico por produto.
        """
        categories = await self.category_repo.ensure_default_categories()
        categories_by_name = {c.name: c for c in categories}
        all_products = await self.product_repo.list_all()
        removed = 0

        # Agrupa produtos (exceto Sorvetes, onde sabores como Oreo são independentes do biscoito Oreo)
        seen_by_norm: dict[tuple[str, bool], Product] = {}
        for prod in sorted(all_products, key=lambda p: p.updated_at, reverse=True):
            is_sorvete = bool(prod.category and prod.category.name == "Sorvetes")
            canon_norm = FuzzyService.normalize_text(prod.canonical_name)
            canonical_sec_name = None if is_sorvete else CANONICAL_PRODUCT_SECTION.get(canon_norm)

            if canonical_sec_name and canonical_sec_name in categories_by_name:
                target_cat = categories_by_name[canonical_sec_name]
                if prod.category_id != target_cat.id:
                    prod.category_id = target_cat.id
                    prod.category = target_cat

            prod.normalized_name = canon_norm
            prod.canonical_name = FuzzyService.canonicalize_display_name(prod.canonical_name)

            key = (canon_norm, is_sorvete)
            if key not in seen_by_norm:
                seen_by_norm[key] = prod
                await self.product_repo.save(prod)
            else:
                winner = seen_by_norm[key]
                # Mescla aliases e porções complementares antes de remover o duplicado
                merged_aliases = list(winner.aliases or [])
                for al in [prod.canonical_name, *(prod.aliases or [])]:
                    if al and al not in merged_aliases and al.lower() != winner.canonical_name.lower():
                        merged_aliases.append(al)
                winner.aliases = merged_aliases
                await self.product_repo.save(winner)
                await self.product_repo.delete(prod)
                removed += 1

        if removed > 0:
            await self.session.commit()
        return removed

    async def process_whatsapp_message(
        self,
        raw_message: str,
        instance_name: str | None = None,
        sender_phone: str | None = None,
        default_section_name: str | None = None,
        source: str = "WHATSAPP",
        reference_timestamp: datetime | None = None,
        replace_section_snapshot: bool = True,
        group_jid: str | None = None,
        allow_create_new: bool | None = None,
    ) -> ParseResultResponse:
        """
        Processa uma mensagem do WhatsApp com regras inteligentes:
        1. Se a mensagem está no PADRÃO DE MENSAGEM PADRÃO (`parsed.is_standard_pattern=True`),
           atualiza existentes e permite cadastrar novos produtos (`allow_create=True`), unificando
           automaticamente produtos semelhantes entre Pizzaria e DiParma sem duplicar.
        2. Se faltar o padrão na mensagem (`parsed.is_standard_pattern=False`), verifica se algum item
           já existe cadastrado no banco e APENAS atualiza o existente (`allow_create=False`), nunca
           adicionando itens fora do padrão!
        """
        categories = await self.category_repo.ensure_default_categories()
        categories_by_name: dict[str, Category] = {c.name: c for c in categories}
        categories_by_norm: dict[str, Category] = {
            FuzzyService.normalize_text(c.name): c for c in categories
        }

        all_products = await self.product_repo.list_all()
        parsed = ParserService.parse_message(raw_message, default_section=default_section_name)

        # Regra central: só cria novos produtos se a mensagem estiver no padrão oficial!
        can_create_new = parsed.is_standard_pattern if allow_create_new is None else (allow_create_new and parsed.is_standard_pattern)

        # Seções explicitamente declaradas na mensagem antes do redirecionamento canônico entre setores
        declared_section_names: set[str] = set(parsed.detected_sections)
        originally_headerless_ids: set[int] = {id(it) for it in parsed.items if not it.section_name}

        # Resolve seções canônicas (ex: Frango -> Açougue, *Batata frita -> Embalagens e Preparos)
        for it in parsed.items:
            if it.normalized_name in CANONICAL_PRODUCT_SECTION:
                it.section_name = CANONICAL_PRODUCT_SECTION[it.normalized_name]
                if id(it) in originally_headerless_ids:
                    declared_section_names.add(it.section_name)
                    if it.section_name not in parsed.detected_sections:
                        parsed.detected_sections.append(it.section_name)

        headerless_items = [it for it in parsed.items if not it.section_name]
        if headerless_items:
            inferred_votes: list[str] = []
            per_item_inferred: list[str | None] = []
            for it in headerless_items:
                inf = self._infer_section_for_item(it, all_products, categories_by_name)
                per_item_inferred.append(inf)
                if inf:
                    inferred_votes.append(inf)

            default_fallback_sec = (
                "Mercado"
                if parsed.report_origin == "DIPARMA"
                else (
                    Counter(inferred_votes).most_common(1)[0][0]
                    if inferred_votes
                    else "Embalagens e Preparos"
                )
            )
            for it, inf in zip(headerless_items, per_item_inferred):
                it.section_name = inf or default_fallback_sec
                declared_section_names.add(it.section_name)
                if it.section_name not in parsed.detected_sections:
                    parsed.detected_sections.append(it.section_name)

        created_count = 0
        updated_count = 0
        incomplete_count = 0
        critical_count = 0
        warning_count = 0
        affected_categories: dict[UUID, Category] = {}
        active_product_ids_by_cat: dict[UUID, set[UUID]] = {}
        now_ts = reference_timestamp or datetime.now(timezone.utc)

        for item in parsed.items:
            sec_name = item.section_name or "Mercado"
            target_category = categories_by_name.get(sec_name) or categories_by_norm.get(
                FuzzyService.normalize_text(sec_name)
            )
            if target_category is None:
                if not can_create_new:
                    continue
                slug = FuzzyService.slugify(sec_name)
                target_category = await self.category_repo.create(
                    name=sec_name,
                    slug=slug,
                    display_order=len(categories) + 1,
                    keywords=[FuzzyService.normalize_text(sec_name)],
                )
                categories.append(target_category)
                categories_by_name[target_category.name] = target_category
                categories_by_norm[FuzzyService.normalize_text(target_category.name)] = target_category

            # 1. Busca primeiro na seção alvo
            match_threshold = settings.FUZZY_MATCH_THRESHOLD if can_create_new else max(88, settings.FUZZY_MATCH_THRESHOLD)
            same_cat_candidates = [p for p in all_products if p.category_id == target_category.id]
            matched_product, _ = FuzzyService.find_best_product_match(
                item.raw_name,
                same_cat_candidates,
                threshold=match_threshold,
            )

            # 2. Se não achou na seção alvo (e não for Sorvetes), busca GLOBALMENTE para jamais duplicar itens entre seções!
            if matched_product is None and target_category.name != "Sorvetes":
                global_candidates = [
                    p for p in all_products if p.category is None or p.category.name != "Sorvetes"
                ]
                matched_product, _ = FuzzyService.find_best_product_match(
                    item.raw_name,
                    global_candidates,
                    threshold=match_threshold,
                )
                if matched_product is not None:
                    # Se o produto tem seção canônica definida, garante que ele fique na seção canônica;
                    # caso contrário, respeita a seção onde ele já estava cadastrado!
                    if item.normalized_name in CANONICAL_PRODUCT_SECTION:
                        matched_product.category_id = target_category.id
                        matched_product.category = target_category
                    elif matched_product.category is not None:
                        target_category = matched_product.category

            # Se a mensagem NÃO está no padrão oficial e o item NÃO existe cadastrado, ignora sem criar!
            if matched_product is None and not can_create_new:
                continue

            # Em mensagem fora do padrão, ignora itens sem valor real de atualização
            if not can_create_new and not item.raw_main_value and not item.sub_attributes:
                continue

            affected_categories[target_category.id] = target_category
            if target_category.id not in active_product_ids_by_cat:
                active_product_ids_by_cat[target_category.id] = set()

            if matched_product is not None:
                existing_ts = (
                    matched_product.updated_at
                    if matched_product.updated_at is None or matched_product.updated_at.tzinfo
                    else matched_product.updated_at.replace(tzinfo=timezone.utc)
                )
                now_ts_aware = now_ts if now_ts.tzinfo else now_ts.replace(tzinfo=timezone.utc)
                is_older_replay = bool(
                    reference_timestamp is not None and existing_ts is not None and now_ts_aware < existing_ts
                )

                if is_older_replay:
                    # Preserva o valor mais recente já gravado (ex: Açougue mais novo que Frios para Frango),
                    # mesclando apenas origens e cortes exclusivos da outra cozinha se não existirem.
                    prev_subs = dict(matched_product.sub_attributes or {})
                    prev_origins = list(prev_subs.get("origens") or [])
                    if parsed.report_origin in ("PIZZARIA", "DIPARMA") and parsed.report_origin not in prev_origins:
                        prev_origins.append(parsed.report_origin)
                    if prev_origins:
                        prev_subs["origens"] = prev_origins
                    if parsed.report_origin == "DIPARMA" and "porcoes_diparma" in item.sub_attributes and "porcoes_diparma" not in prev_subs:
                        prev_subs["porcoes_diparma"] = item.sub_attributes["porcoes_diparma"]
                    elif parsed.report_origin == "PIZZARIA" and "porcoes" in item.sub_attributes and "porcoes" not in prev_subs:
                        prev_subs["porcoes"] = item.sub_attributes["porcoes"]
                    merged_subs = prev_subs
                    eff_main_val = matched_product.raw_main_value
                    eff_num_qty = matched_product.numeric_quantity
                    eff_unit = matched_product.unit
                    eff_incomplete = matched_product.is_incomplete_data
                    eff_updated_at = matched_product.updated_at
                else:
                    merged_subs = self._merge_sub_attributes(
                        matched_product.sub_attributes,
                        item.sub_attributes,
                        parsed.report_origin,
                    )
                    eff_main_val = item.raw_main_value if item.raw_main_value or parsed.is_standard_pattern else matched_product.raw_main_value
                    eff_num_qty = item.numeric_quantity if item.raw_main_value or parsed.is_standard_pattern else matched_product.numeric_quantity
                    eff_unit = item.unit if item.raw_main_value or parsed.is_standard_pattern else matched_product.unit
                    eff_incomplete = item.is_incomplete_data
                    eff_updated_at = now_ts

                status_val, needs_restock, _ = self.evaluate_stock_status(
                    raw_main_value=eff_main_val,
                    numeric_quantity=eff_num_qty,
                    sub_attributes=merged_subs,
                    is_incomplete_data=eff_incomplete,
                )

                if status_val == StockStatus.CRITICAL:
                    critical_count += 1
                elif status_val in (StockStatus.WARNING, StockStatus.NEEDS_ACTION):
                    warning_count += 1
                if eff_incomplete:
                    incomplete_count += 1

                raw_clean = item.raw_name.strip()
                current_aliases = list(matched_product.aliases or [])
                if (
                    raw_clean.lower() != matched_product.canonical_name.lower()
                    and raw_clean not in current_aliases
                    and raw_clean.lower() not in [a.lower() for a in current_aliases]
                ):
                    current_aliases.append(raw_clean)

                matched_product.aliases = current_aliases
                matched_product.raw_main_value = eff_main_val
                matched_product.numeric_quantity = eff_num_qty
                matched_product.unit = eff_unit
                matched_product.sub_attributes = merged_subs
                matched_product.stock_status = status_val
                matched_product.needs_restock = needs_restock
                matched_product.is_incomplete_data = eff_incomplete
                matched_product.updated_at = eff_updated_at
                await self.product_repo.save(matched_product)
                active_product_ids_by_cat[target_category.id].add(matched_product.id)
                updated_count += 1
            else:
                merged_subs = self._merge_sub_attributes(None, item.sub_attributes, parsed.report_origin)
                status_val, needs_restock, _ = self.evaluate_stock_status(
                    raw_main_value=item.raw_main_value,
                    numeric_quantity=item.numeric_quantity,
                    sub_attributes=merged_subs,
                    is_incomplete_data=item.is_incomplete_data,
                )

                if status_val == StockStatus.CRITICAL:
                    critical_count += 1
                elif status_val in (StockStatus.WARNING, StockStatus.NEEDS_ACTION):
                    warning_count += 1
                if item.is_incomplete_data:
                    incomplete_count += 1

                initial_aliases: list[str] = []
                if item.raw_name.strip().lower() != item.canonical_candidate.lower():
                    initial_aliases.append(item.raw_name.strip())

                new_product = Product(
                    category_id=target_category.id,
                    canonical_name=item.canonical_candidate,
                    normalized_name=item.normalized_name,
                    aliases=initial_aliases,
                    raw_main_value=item.raw_main_value,
                    numeric_quantity=item.numeric_quantity,
                    unit=item.unit,
                    sub_attributes=merged_subs,
                    stock_status=status_val,
                    needs_restock=needs_restock,
                    is_incomplete_data=item.is_incomplete_data,
                    updated_at=now_ts,
                )
                new_product.category = target_category
                await self.product_repo.create(new_product)
                all_products.append(new_product)
                active_product_ids_by_cat[target_category.id].add(new_product.id)
                created_count += 1

        # Se mensagem avulsa não casou com nenhum produto cadastrado, ignora silenciosamente
        if not can_create_new and updated_count == 0 and created_count == 0:
            return ParseResultResponse(
                status="ignored",
                instance_name=instance_name or settings.EVOLUTION_INSTANCE_NAME,
                group_jid=group_jid or settings.TARGET_GROUP_JID,
                affected_sections=[],
                parsed_items_count=0,
                created_products_count=0,
                updated_products_count=0,
                incomplete_items_count=0,
                critical_items_count=0,
                warning_items_count=0,
                unrecognized_lines=parsed.unrecognized_lines,
                log_id=None,
            )

        primary_categories: dict[UUID, Category] = {
            cid: cat
            for cid, cat in affected_categories.items()
            if cat.name in declared_section_names or len(active_product_ids_by_cat.get(cid, set())) >= 3
        }
        if not primary_categories:
            primary_categories = affected_categories

        for cat in primary_categories.values():
            await self.category_repo.touch_timestamp(cat, source=source, updated_at=now_ts)

        # Limpeza inteligente de retrato por origem (`PIZZARIA` vs `DIPARMA`):
        # Remove itens obsoletos APENAS se pertencerem exclusivamente à mesma origem do relatório atual,
        # evitando que um relatório da Pizzaria apague itens exclusivos do DiParma e vice-versa!
        if replace_section_snapshot and parsed.is_standard_pattern and parsed.report_origin in ("PIZZARIA", "DIPARMA"):
            origin = parsed.report_origin
            for cat_id, active_ids in active_product_ids_by_cat.items():
                cat_obj = affected_categories.get(cat_id)
                is_declared_cat = bool(cat_obj and cat_obj.name in declared_section_names)
                if origin == "PIZZARIA" and is_declared_cat and len(active_ids) >= 3:
                    cat_prods = [p for p in all_products if p.category_id == cat_id and p.id not in active_ids]
                    for stale_prod in cat_prods:
                        prod_origins = list((stale_prod.sub_attributes or {}).get("origens") or ["PIZZARIA"])
                        if prod_origins == ["PIZZARIA"]:
                            await self.product_repo.delete(stale_prod)
                elif origin == "DIPARMA" and sum(len(s) for s in active_product_ids_by_cat.values()) >= 10:
                    cat_prods = [p for p in all_products if p.category_id == cat_id and p.id not in active_ids]
                    for stale_prod in cat_prods:
                        prod_origins = list((stale_prod.sub_attributes or {}).get("origens") or [])
                        if prod_origins == ["DIPARMA"]:
                            await self.product_repo.delete(stale_prod)

        eff_instance = instance_name or settings.EVOLUTION_INSTANCE_NAME
        stock_log = await self.log_repo.create(
            instance_name=eff_instance,
            sender_phone=sender_phone or group_jid,
            raw_message=raw_message,
            parsed_items_count=created_count + updated_count,
            unrecognized_lines=parsed.unrecognized_lines,
        )

        await self.session.commit()

        return ParseResultResponse(
            status="processed",
            instance_name=eff_instance,
            group_jid=group_jid or settings.TARGET_GROUP_JID,
            affected_sections=[c.name for c in primary_categories.values()],
            parsed_items_count=created_count + updated_count,
            created_products_count=created_count,
            updated_products_count=updated_count,
            incomplete_items_count=incomplete_count,
            critical_items_count=critical_count,
            warning_items_count=warning_count,
            unrecognized_lines=parsed.unrecognized_lines,
            log_id=str(stock_log.id),
        )

    async def get_dashboard_data(self) -> DashboardResponse:
        """Monta o payload consolidado do painel web (GET /api/v1/dashboard)."""
        await self.category_repo.ensure_default_categories()
        categories = await self.category_repo.list_all_ordered(include_products=True)
        now = datetime.now(timezone.utc)

        sections_health: list[CategoryHealthResponse] = []
        missing_summary: list[MissingProductSummaryItem] = []
        sections_with_products: list[DashboardSectionWithProducts] = []

        total_products = 0
        critical_total = 0
        warning_total = 0
        portioned_total = 0
        ok_total = 0
        incomplete_total = 0
        stale_sections_count = 0

        status_priority = {
            StockStatus.CRITICAL: 0,
            StockStatus.NEEDS_ACTION: 1,
            StockStatus.WARNING: 2,
            StockStatus.PORTIONED: 3,
            StockStatus.OK: 4,
        }

        for cat in categories:
            health = self.compute_category_health(cat, now=now)
            sections_health.append(health)
            if health.is_stale and health.total_products > 0:
                stale_sections_count += 1

            sorted_products = sorted(
                cat.products or [],
                key=lambda p: (status_priority.get(p.stock_status, 9), p.canonical_name.lower()),
            )

            product_responses: list[ProductResponse] = []
            for prod in sorted_products:
                # Recalcula dinamicamente para garantir consistência imediata com as regras atuais
                dyn_status, dyn_restock, status_note = self.evaluate_stock_status(
                    raw_main_value=prod.raw_main_value,
                    numeric_quantity=prod.numeric_quantity,
                    sub_attributes=prod.sub_attributes,
                    is_incomplete_data=prod.is_incomplete_data,
                )
                prod.stock_status = dyn_status
                prod.needs_restock = dyn_restock

                total_products += 1
                if dyn_status == StockStatus.CRITICAL:
                    critical_total += 1
                elif dyn_status in (StockStatus.WARNING, StockStatus.NEEDS_ACTION):
                    warning_total += 1
                elif dyn_status == StockStatus.PORTIONED:
                    portioned_total += 1
                else:
                    ok_total += 1

                if prod.is_incomplete_data:
                    incomplete_total += 1

                prod_resp = ProductResponse(
                    id=prod.id,
                    category_id=prod.category_id,
                    category_name=cat.name,
                    canonical_name=prod.canonical_name,
                    normalized_name=prod.normalized_name,
                    aliases=list(prod.aliases or []),
                    raw_main_value=prod.raw_main_value,
                    numeric_quantity=float(prod.numeric_quantity) if prod.numeric_quantity is not None else None,
                    unit=prod.unit,
                    sub_attributes=dict(prod.sub_attributes or {}),
                    stock_status=dyn_status,
                    needs_restock=dyn_restock,
                    is_incomplete_data=prod.is_incomplete_data,
                    status_note=status_note,
                    updated_at=prod.updated_at,
                )
                product_responses.append(prod_resp)

                if dyn_restock or dyn_status in (
                    StockStatus.CRITICAL,
                    StockStatus.WARNING,
                    StockStatus.NEEDS_ACTION,
                ):
                    missing_summary.append(
                        MissingProductSummaryItem(
                            id=prod.id,
                            canonical_name=prod.canonical_name,
                            category_id=cat.id,
                            category_name=cat.name,
                            raw_main_value=prod.raw_main_value,
                            sub_attributes=dict(prod.sub_attributes or {}),
                            stock_status=dyn_status.value,
                            status_note=status_note,
                            is_incomplete_data=prod.is_incomplete_data,
                            updated_at=prod.updated_at,
                        )
                    )

            sections_with_products.append(
                DashboardSectionWithProducts(
                    health=health,
                    products=product_responses,
                )
            )

        missing_summary.sort(
            key=lambda item: (
                0 if item.stock_status == "CRITICAL" else 1,
                item.category_name,
                item.canonical_name.lower(),
            )
        )

        stats = DashboardStats(
            total_sections=len(categories),
            stale_sections_count=stale_sections_count,
            total_products=total_products,
            critical_products_count=critical_total,
            warning_products_count=warning_total,
            portioned_products_count=portioned_total,
            ok_products_count=ok_total,
            incomplete_products_count=incomplete_total,
        )

        return DashboardResponse(
            generated_at=now,
            stale_threshold_hours=settings.STALE_SECTION_HOURS,
            stats=stats,
            sections_health=sections_health,
            missing_products_summary=missing_summary,
            sections=sections_with_products,
        )

    async def create_product_manual(self, payload: ProductCreate) -> ProductResponse:
        category = await self.category_repo.get_by_id(payload.category_id)
        if category is None:
            raise EntityNotFoundError("Seção", payload.category_id)

        num_q = payload.numeric_quantity
        unit_q = payload.unit
        if num_q is None and payload.raw_main_value:
            num_q, extracted_unit = ParserService.extract_numeric_and_unit(payload.raw_main_value)
            if not unit_q:
                unit_q = extracted_unit

        status_val, needs_restock, _ = self.evaluate_stock_status(
            raw_main_value=payload.raw_main_value,
            numeric_quantity=num_q,
            sub_attributes=payload.sub_attributes,
            is_incomplete_data=payload.is_incomplete_data,
        )

        now = datetime.now(timezone.utc)
        product = Product(
            category_id=category.id,
            canonical_name=payload.canonical_name.strip(),
            normalized_name=FuzzyService.normalize_text(payload.canonical_name),
            aliases=payload.aliases,
            raw_main_value=payload.raw_main_value.strip(),
            numeric_quantity=num_q,
            unit=unit_q,
            sub_attributes=payload.sub_attributes,
            stock_status=status_val,
            needs_restock=needs_restock,
            is_incomplete_data=payload.is_incomplete_data,
            updated_at=now,
        )
        await self.product_repo.create(product)
        await self.category_repo.touch_timestamp(category, source="WEB", updated_at=now)
        await self.session.commit()
        product.category = category
        return self.to_product_response(product, category_name=category.name)

    async def update_product_manual(
        self,
        product_id: UUID,
        payload: ProductUpdate,
    ) -> ProductResponse:
        product = await self.product_repo.get_by_id(product_id)
        if product is None:
            raise EntityNotFoundError("Produto", product_id)

        if payload.category_id is not None and payload.category_id != product.category_id:
            new_cat = await self.category_repo.get_by_id(payload.category_id)
            if new_cat is None:
                raise EntityNotFoundError("Seção", payload.category_id)
            product.category_id = new_cat.id
            product.category = new_cat

        if payload.canonical_name is not None:
            product.canonical_name = payload.canonical_name.strip()
            product.normalized_name = FuzzyService.normalize_text(payload.canonical_name)

        if payload.raw_main_value is not None:
            product.raw_main_value = FuzzyService.normalize_inline_terms(payload.raw_main_value.strip())
            num_q, unit_q = ParserService.extract_numeric_and_unit(product.raw_main_value)
            product.numeric_quantity = payload.numeric_quantity if payload.numeric_quantity is not None else num_q
            product.unit = payload.unit if payload.unit is not None else unit_q
        else:
            if payload.numeric_quantity is not None:
                product.numeric_quantity = payload.numeric_quantity
            if payload.unit is not None:
                product.unit = FuzzyService.normalize_unit(payload.unit)

        if payload.sub_attributes is not None:
            product.sub_attributes = payload.sub_attributes

        if payload.aliases is not None:
            product.aliases = payload.aliases

        if payload.is_incomplete_data is not None:
            product.is_incomplete_data = payload.is_incomplete_data
        elif payload.raw_main_value is not None and payload.raw_main_value.strip():
            product.is_incomplete_data = False

        calc_status, calc_restock, _ = self.evaluate_stock_status(
            raw_main_value=product.raw_main_value,
            numeric_quantity=product.numeric_quantity,
            sub_attributes=product.sub_attributes,
            is_incomplete_data=product.is_incomplete_data,
        )
        if payload.stock_status_override is not None:
            product.stock_status = payload.stock_status_override
            product.needs_restock = payload.stock_status_override in (
                StockStatus.CRITICAL,
                StockStatus.WARNING,
                StockStatus.NEEDS_ACTION,
            )
        else:
            product.stock_status = calc_status
            product.needs_restock = calc_restock

        now = datetime.now(timezone.utc)
        product.updated_at = now
        await self.product_repo.save(product)

        if payload.update_section_timestamp and product.category is not None:
            await self.category_repo.touch_timestamp(product.category, source="WEB", updated_at=now)

        await self.session.commit()
        return self.to_product_response(product)

    async def delete_product(self, product_id: UUID) -> None:
        product = await self.product_repo.get_by_id(product_id)
        if product is None:
            raise EntityNotFoundError("Produto", product_id)
        await self.product_repo.delete(product)
        await self.session.commit()
