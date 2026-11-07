from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.fuzzy_service import FuzzyService


# Marcadores exclusivos de blocos da Comida Italiana (DiParma): ▶️ (U+25B6) e ➡️ (U+27A1)
DIPARMA_ITEM_MARKER_PATTERN = re.compile(r"^[\s'\"´`⁸⁰¹²³⁴⁵⁶⁷⁹]*[▶➡][\ufe0e\ufe0f]?\s*(?P<name>.+)$")

# Regex amplo para remoção de emojis, símbolos pictográficos e seletores de variação
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U000025A0-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)

# Marcadores de lista no início da linha
LIST_MARKER_PATTERN = re.compile(r"^[\s●•▪▫‣⁃\*—–\-]+")

# Mapeamento de cabeçalhos conhecidos para o nome oficial da seção
KNOWN_SECTION_HEADERS: dict[str, str] = {
    "frios": "Frios",
    "laticinios": "Frios",
    "acougue": "Açougue",
    "carnes": "Açougue",
    "proteinas": "Açougue",
    "mercado": "Mercado",
    "mercearia": "Mercado",
    "hortifrutis": "Hortifrutis",
    "hortifruti": "Hortifrutis",
    "horti": "Hortifrutis",
    "frutas e verduras": "Hortifrutis",
    "legumes e verduras": "Hortifrutis",
    "produtos de limpeza": "Produtos de Limpeza",
    "produto de limpeza": "Produtos de Limpeza",
    "material de limpeza": "Produtos de Limpeza",
    "limpeza": "Produtos de Limpeza",
    "embalagens e preparos": "Embalagens e Preparos",
    "embalagens": "Embalagens e Preparos",
    "preparos": "Embalagens e Preparos",
    "massas e caixas": "Embalagens e Preparos",
    "sorvetes": "Sorvetes",
    "sorvete": "Sorvetes",
}

DIPARMA_REPORT_HEADERS: set[str] = {
    "relacao produtos diparma",
    "relacao de produtos diparma",
    "relacao diparma",
    "produtos diparma",
    "estoque diparma",
    "diparma",
    "di parma",
}

# Sub-cabeçalhos que mantêm ou definem a seção mas adicionam tag de subcategoria
KNOWN_SUBSECTION_HEADERS: dict[str, tuple[str, str]] = {
    "para suco": ("Hortifrutis", "Para Suco"),
    "sucos": ("Hortifrutis", "Para Suco"),
    "polpas e sucos": ("Hortifrutis", "Para Suco"),
    "folhas": ("Hortifrutis", "Folhas"),
    "verduras": ("Hortifrutis", "Folhas"),
    "temperos verdes": ("Hortifrutis", "Folhas"),
}

# Palavras-chave de estado secundário (sub-atributos) no início da linha
SUB_ATTRIBUTE_KEYWORDS: dict[str, str] = {
    "aberto": "aberto",
    "aberta": "aberto",
    "abertos": "aberto",
    "abertas": "aberto",
    "fechado": "fechado",
    "fechada": "fechado",
    "fechados": "fechado",
    "fechadas": "fechado",
    "porcao": "porcoes",
    "porcoes": "porcoes",
    "porca": "porcoes",
    "porc": "porcoes",
    "cozido": "cozido",
    "cozida": "cozido",
    "cozidos": "cozido",
    "cozidas": "cozido",
    "cozinhando": "cozido",
    "congelado": "congelado",
    "congelada": "congelado",
    "congelados": "congelado",
    "congeladas": "congelado",
    "ralado": "ralado",
    "ralada": "ralado",
    "ralados": "ralado",
    "cortado": "cortado",
    "cortada": "cortado",
    "fatiado": "cortado",
    "fatiada": "cortado",
    "picado": "cortado",
    "picada": "cortado",
    "desfiado": "desfiado",
    "desfiada": "desfiado",
    "em uso": "em_uso",
    "uso": "em_uso",
    "penca": "pencas",
    "pencas": "pencas",
    "panela": "panelas",
    "panelas": "panelas",
}

UNIT_TOKENS_REGEX = (
    r"g|gr|grs|gm|gms|gramas?|kg|kgs|kilos?|l|lt|lts|ml|uni|umi|unid|und|unidades?|pct|pcts|pacotes?|cx|cxs|caixas?|"
    r"vasilhas?|panelas?|barras?|barrinhas?|sacos?|sach[eê]s?|baldes?|fardos?|garrafas?|latas?|pe[cç]as?|p[cç]s?|p[eé]s?|"
    r"placas?|caixotes?|potes?|bisnagas?|gal[oõaã](?:es|o)?|rolos?"
)

# Padrão especial para sub-linha de porção com peso antes de dois-pontos: "150 porção: 00", "100 porca : 00"
WEIGHT_FIRST_PORTION_PATTERN = re.compile(
    r"^(?P<weight>\d{2,4}g?)\s*por[cç](?:oes|ao|a|ões|ão)?\s*:\s*(?P<qty>\d+|tem\b.*|pouc[oa]\b.*)$",
    flags=re.IGNORECASE,
)

# Padrão de linha que começa com quantidade seguida de indicador de porção/sub-item
QUANTITY_SUBLINE_PATTERN = re.compile(
    r"^(?P<qty>\d+(?:[.,/]\d+)?)\s*"
    r"(?P<kind>por[cç](?:oes|ao|a|ões|ão)?|panelas?|vasilhas?|pe[cç]as?|pencas?|"
    r"abert[oa]s?|fechad[oa]s?|cozid[oa]s?|congelad[oa]s?|ralad[oa]s?|cortad[oa]s?|fatiad[oa]s?)\b"
    r"(?P<rest>.*)$",
    flags=re.IGNORECASE,
)

# Padrão para linha que contém APENAS quantidade ou status (Caso 2: valor quebrado na linha seguinte, ex: "06 uni")
STANDALONE_VALUE_LINE_PATTERN = re.compile(
    rf"^(?:"
    rf"\d+(?:[.,/]\d+)?(?:\s*(?:{UNIT_TOKENS_REGEX})"
    rf"(?:\s+e\s+mei[oa]|\s+de\s+[\w\s]+|\s+fechad[oa]s?|\s+abert[oa]s?|\s+pront[oa]s?)?)?"
    rf"(?:\s+e\s+mei[oa])?"
    rf"(?:\s*\+\s*\d+[\w\s]*)*"
    rf"|tem+(?:\s+[\w\s]+)?"
    rf"|sim"
    rf"|pouco|pouca|acabou|falta|trazer|fazer|comprar|zerado|nada|precisa"
    rf"|meia\s+[\w\s]+|meio\s+[\w\s]+|abaixo\s+de\s+[\w\s]+|acima\s+de\s+[\w\s]+"
    rf")$",
    flags=re.IGNORECASE,
)

# Padrão Caso 1: Linha sem dois-pontos com sufixo quantitativo ou status no final
INLINE_SUFFIX_VALUE_PATTERN = re.compile(
    rf"^(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-\(\)/&]*?)\s+"
    rf"(?P<value>"
    rf"(?:abaixo\s+de\s+[\w\s/]+|acima\s+de\s+[\w\s/]+|meia?\s+(?:vasilha|caixa|caixote|saco|barra|panela|unidade|pe[cç]a)[\w\s]*)"
    rf"|(?:\d+(?:[.,/]\d+)?\s*(?:pct|pcts|pacotes?)?\s+e\s+mei[oa])"
    rf"|(?:\d+(?:[.,/]\d+)?\s*(?:{UNIT_TOKENS_REGEX}|por[cç](?:oes|ao|a|ões|ão)?)\b[\w\s\+]*)"
    rf"|(?:\d+(?:[.,]\d+)?)"
    rf"|(?:tem+|pouco|pouca|acabou|falta|trazer|fazer|comprar|zerado)"
    rf")$",
    flags=re.IGNORECASE,
)

# Padrão reverso em mensagem solta: "Acabou limão", "Trazer pão de hot dog", "Falta mussarela"
ACTION_PREFIX_ITEM_PATTERN = re.compile(
    r"^(?P<action>acabou|falta|trazer|comprar|repor|precisa(?:\s+de)?)\s+(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-\(\)&]{1,45})$",
    flags=re.IGNORECASE,
)

# Extração de número + unidade de um raw_main_value
NUMERIC_UNIT_EXTRACT_PATTERN = re.compile(
    rf"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>{UNIT_TOKENS_REGEX}|por[cç](?:oes|ao|a|ões|ão)?)?",
    flags=re.IGNORECASE,
)


@dataclass
class ParsedProductItem:
    """Representa um produto extraído e estruturado pelo ParserService."""

    raw_name: str
    canonical_candidate: str
    normalized_name: str
    raw_main_value: str = ""
    numeric_quantity: Decimal | None = None
    unit: str | None = None
    sub_attributes: dict[str, Any] = field(default_factory=dict)
    section_name: str | None = None
    is_incomplete_data: bool = False
    report_origin: str = "PIZZARIA"


@dataclass
class ParsedMessageResult:
    """Resultado completo da interpretação de uma mensagem do WhatsApp."""

    detected_sections: list[str] = field(default_factory=list)
    items: list[ParsedProductItem] = field(default_factory=list)
    unrecognized_lines: list[str] = field(default_factory=list)
    report_origin: str = "PIZZARIA"
    is_standard_pattern: bool = False


class ParserService:
    """
    Máquina de estados para leitura e higienização de relatórios de estoque
    da Pizzaria (Frios, Açougue, Mercado, Hortifrutis, Limpeza, Embalagens, Sorvetes)
    e da Comida Italiana (RELAÇÃO PRODUTOS DIPARMA), além de atualizações avulsas.
    """

    @staticmethod
    def clean_line(raw_line: str) -> str:
        """
        Remove emojis, marcadores de lista (●, •, *, -) e ruídos isolados,
        preservando o conteúdo textual e pontuação relevante (: / + & ?).
        """
        if not raw_line:
            return ""
        without_emojis = EMOJI_PATTERN.sub(" ", raw_line)
        cleaned = without_emojis.strip()
        # Remove caracteres órfãos como aspas isoladas ou expoentes (' , ⁸)
        cleaned = re.sub(r"^['\"´`⁸⁰¹²³⁴⁵⁶⁷⁹\s]+|['\"´`⁸⁰¹²³⁴⁵⁶⁷⁹\s]+$", "", cleaned)
        cleaned = re.sub(r"^\*+|\*+$", "", cleaned).strip()
        cleaned = LIST_MARKER_PATTERN.sub("", cleaned).strip()
        cleaned = re.sub(r"\*+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @classmethod
    def _is_diparma_message(cls, raw_message: str) -> bool:
        """Detecta se a mensagem é a Relação de Produtos DiParma (Comida Italiana)."""
        norm_head = FuzzyService.normalize_text(raw_message[:120])
        if any(h in norm_head for h in ("relacao produtos diparma", "produtos diparma", "estoque diparma")):
            return True
        arrow_blocks = len(re.findall(r"[▶➡]", raw_message))
        return arrow_blocks >= 2

    @classmethod
    def _normalize_diparma_subline(cls, raw_line: str) -> str:
        """
        Higieniza sublinhas do padrão DiParma:
        - Converte 'O0'/'O2' (letra O no lugar de zero) -> '00'/'02'
        - Padroniza '15KILOS' -> '15kg', '300gr'/'500grs'/'100 GM'/'150 GRAMA' -> '300g'/'500g'/'100g'/'150g'
        - Separa números colados em palavras ('10FILÉ' -> '10 filé', '14FECHADAS' -> '14 fechadas', '+03placas' -> '+ 03 placas')
        """
        cleaned = cls.clean_line(raw_line)
        if not cleaned:
            return ""
        # Corrige letra O digitada no lugar do zero: O0PACOTE -> 00PACOTE, O2PACOTE -> 02PACOTE
        cleaned = re.sub(r"\b[Oo](\d)", r"0\1", cleaned)
        # Separa sinal '+' colado
        cleaned = re.sub(r"\+\s*(\d)", r"+ \1", cleaned)
        # Padroniza pesos e quilos colados ou por extenso
        cleaned = re.sub(r"(\d+)\s*(?:kilos?|kgs?)\b", r"\1kg", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"(\d+)\s*(?:gramas?|grs?|gms?)\b", r"\1g", cleaned, flags=re.IGNORECASE)
        # Separa números colados em palavras de 2+ letras (preservando 100g, 3kg, 4L)
        cleaned = re.sub(r"(\d)([A-Za-zÀ-ÿ]{2,})", r"\1 \2", cleaned)
        # Remove sufixo redundante "PARA O DI PARMA"
        cleaned = re.sub(r"\s+para\s+o\s+di\s*parma\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = FuzzyService.normalize_inline_terms(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @classmethod
    def _line_has_positive_qty(cls, text: str) -> bool:
        norm = FuzzyService.remove_accents(text.lower()).strip()
        if not norm:
            return False
        m = re.match(r"^[+\s]*(\d+(?:[.,]\d+)?)", norm)
        if m:
            try:
                return float(m.group(1).replace(",", ".")) > 0
            except ValueError:
                pass
        nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", norm)]
        if nums:
            return any(n > 0 for n in nums)
        return bool(re.search(r"\b(?:tem|sim|meia|meio|pouco|pouca)\b", norm))

    @classmethod
    def _parse_diparma_message(cls, raw_message: str) -> ParsedMessageResult:
        """
        Parser especializado para `RELAÇÃO PRODUTOS DIPARMA`:
        Cada item inicia com `▶️` ou `➡️` seguido de linhas de aberto, fechado, porções, parmegiana, filés ou panelas.
        """
        result = ParsedMessageResult(
            report_origin="DIPARMA",
            is_standard_pattern=True,
        )

        blocks: list[tuple[str, list[str]]] = []
        current_name: str | None = None
        current_lines: list[str] = []

        for raw_line in raw_message.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue

            marker_match = DIPARMA_ITEM_MARKER_PATTERN.match(stripped)
            if marker_match:
                if current_name:
                    blocks.append((current_name, current_lines))
                current_name = cls.clean_line(marker_match.group("name"))
                current_lines = []
                continue

            cl = cls.clean_line(stripped)
            if not cl:
                continue
            norm_cl = FuzzyService.normalize_text(cl)
            if norm_cl in DIPARMA_REPORT_HEADERS:
                continue

            if current_name is not None:
                norm_sub = cls._normalize_diparma_subline(stripped)
                if norm_sub:
                    current_lines.append(norm_sub)
            else:
                result.unrecognized_lines.append(cl)

        if current_name:
            blocks.append((current_name, current_lines))

        for prod_name, sublines in blocks:
            if not prod_name:
                continue

            aberto_list: list[str] = []
            em_uso_list: list[str] = []
            panelas_list: list[str] = []
            porcoes_list: list[str] = []
            closed_lines: list[str] = []
            needs_precisa = False

            for sline in sublines:
                lower_s = FuzzyService.remove_accents(sline.lower())

                if re.search(r"\b(?:precisa|trazer|comprar|falta|repor)\b", lower_s):
                    needs_precisa = True

                # Continuação "+ 03 placas" cola na última linha principal
                if sline.startswith("+") and closed_lines:
                    closed_lines[-1] = f"{closed_lines[-1]} {sline}"
                    continue

                clean_sline = re.sub(r"\s*\bprecisa!?\b", "", sline, flags=re.IGNORECASE).strip(" !.")

                if re.search(r"\bem\s+uso\b", lower_s):
                    if cls._line_has_positive_qty(clean_sline):
                        em_uso_list.append(clean_sline)
                elif re.search(r"\babert[oa]s?\b", lower_s):
                    if cls._line_has_positive_qty(clean_sline) or "pouc" in lower_s:
                        aberto_list.append(clean_sline)
                elif re.search(r"\b(?:panelas?|cozinhand[oa]?|em\s+producao)\b", lower_s):
                    if cls._line_has_positive_qty(clean_sline):
                        panelas_list.append(clean_sline)
                elif re.search(
                    r"\b(?:por[cç](?:oes|ao|a)?|parmegiana|escalope|medalhao|pure)\b|\bfile\s+(?:de|cortado)\b",
                    lower_s,
                ):
                    porcoes_list.append(clean_sline)
                else:
                    closed_lines.append(clean_sline)

            # Determina o valor principal (fechado / quilos / peças / pacotes / Tem)
            positive_closed = [c for c in closed_lines if cls._line_has_positive_qty(c)]
            zero_closed = [c for c in closed_lines if not cls._line_has_positive_qty(c)]

            raw_main_value = ""
            if positive_closed:
                raw_main_value = " + ".join(positive_closed)
            elif zero_closed:
                raw_main_value = "00"
            elif porcoes_list or aberto_list or em_uso_list or panelas_list:
                raw_main_value = "00"

            if needs_precisa and raw_main_value == "00":
                raw_main_value = "00 (trazer)"

            sub_attrs: dict[str, Any] = {}
            if porcoes_list:
                sub_attrs["porcoes_diparma"] = porcoes_list
            if aberto_list:
                sub_attrs["aberto"] = " | ".join(aberto_list)
            if em_uso_list:
                sub_attrs["em_uso"] = " | ".join(em_uso_list)
            if panelas_list:
                sub_attrs["panelas"] = " | ".join(panelas_list)
            if needs_precisa:
                sub_attrs["acao"] = "trazer"

            num_q, unit_q = cls.extract_numeric_and_unit(raw_main_value)
            is_inc = not bool(raw_main_value) and not bool(sub_attrs)

            item = ParsedProductItem(
                raw_name=prod_name,
                canonical_candidate=FuzzyService.canonicalize_display_name(prod_name),
                normalized_name=FuzzyService.normalize_text(prod_name),
                raw_main_value=raw_main_value,
                numeric_quantity=num_q,
                unit=unit_q,
                sub_attributes=sub_attrs,
                section_name=None,
                is_incomplete_data=is_inc,
                report_origin="DIPARMA",
            )
            result.items.append(item)

        # Deduplica dentro do próprio relatório DiParma
        dedup: dict[str, ParsedProductItem] = {}
        for it in result.items:
            dedup[it.normalized_name] = it
        result.items = list(dedup.values())
        return result

    @classmethod
    def _split_into_logical_lines(cls, raw_message: str) -> list[str]:
        """
        Pré-processa a mensagem para suportar tanto mensagens com quebras de linha (\n)
        quanto mensagens coladas em linha única.
        """
        text = EMOJI_PATTERN.sub(" ", raw_message)
        # 1. Marcadores ● e • sempre iniciam nova linha lógica
        text = re.sub(r"[●•▪▫‣]", "\n", text)

        # 2. Cabeçalhos de seção e sub-cabeçalhos colados na mesma linha
        text = re.sub(
            r"(?:^|\s+)(\*?AÇOUGUE\b|\*?ACOGUE\b|\*?Frios\b|\*?Mercado\b|\*?Hortifrutis?\b|\*?Produtos\s+de\s+limpeza\b|\*?SORVETES\s*:?|\*?Para\s+Suco\b|\*?FOLHAS\b)\s*:?",
            r"\n\1\n",
            text,
            flags=re.IGNORECASE,
        )

        # 3. Sub-atributos colados na mesma linha
        text = re.sub(
            r"\s+(?=(?:150|100)\s+por[cç](?:ão|ao|a|ões|oes)\s*:)",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?<!150)(?<!100)(?<!Calabresa)(?<!Massas)(?<!Massa)\s+(?=(?:Abert[oa]s?|Fechad[oa]s?|Por[cç][oõ]es|Por[cç][aã]o|Porca|Cozid[oa]s?|Congelad[oa]s?|Ralad[oa]s?|Cortad[oa]s?|Em\s+uso|Pencas?)\s*:)",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?<!\d)\s+(?=Por[cç][oõ]es\s+\d+\s+Por[cç][oõ]es\b)",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?<!Porções)(?<!Porção)(?<!porções)(?<!porção)(?<!:)\s+(?=\d+\s+(?:Por[cç][oõ]es|por[cç][oõ]es|porca|Panelas?\s+pront[oa]s?|panela\s+em\s+produ[cç][aã]o|pe[cç]as?\s*:))",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(\b\d+\s+barras?)\s+(\d+\s+vasilhas?\b)",
            r"\1\n\2",
            text,
            flags=re.IGNORECASE,
        )

        # 4. Produtos colados na mesma linha após um valor finalizado
        value_end_group = (
            r"(\b\d+(?:[.,]\d+)?\s*(?:[Kk][Gg]|[Gg]|[Ll]|ml|uni|umi|unidade|unidades|barras?|barrinhas?|vasilhas?(?:\s+de\s+pur[eê])?|latas?|balde|fechad[oa]|p[eé]|placas?)\b"
            r"|\b\d+\s+de\s+\d+g?\b"
            r"|\b\d+\s+[Pp]ct\s+e\s+[Mm]eio\b"
            r"|\b00\s+trazer\b"
            r"|\b\d+\s+panela\s+em\s+produ[cç][aã]o\b"
            r"|\b\d+\s+[Pp]anelas?\s+pront[oa]s?\b"
            r"|\b(?:[Tt]em+|[Pp]ouc[oa]|[Tt]razer|[Ff]azer)\b"
            r"|:\s*\d{1,2}\b)"
        )
        next_prod_lookahead = (
            r"\s+(?=(?!Vasilhas?\b|Por[cç][oõ]es\b|Panelas?\b|Fechad[oa]\b|Abert[oa]\b|Barrinhas?\b)"
            r"[A-ZÀ-Ÿ][A-Za-zÀ-ÿ0-9&\s]{0,32}?"
            r"(?:\s*:|\s+\d+(?:[.,]\d+)?\s*(?:[Kk][Gg]|[Gg]|[Ll]|uni|umi|unidade|p[eé]|[Pp]ct|[Vv]asilhas?)\b|\s+\b00\b|\s+(?:[Tt]em+|[Tt]razer|[Pp]ouc[oa])\b))"
        )
        for _ in range(4):
            text = re.sub(value_end_group + next_prod_lookahead, r"\1\n", text)

        text = re.sub(
            r"(\b\d+)\s+(?=(?!Vasilhas?\b|Por[cç][oõ]es\b|Panelas?\b|Barras?\b|Barrinhas?\b|Unidades?\b|Pct\b|Pe[cç]as?\b|Placas?\b|Pacotes?\b|Rolos?\b|de\b|e\b)"
            r"[A-ZÀ-Ÿ][A-Za-zÀ-ÿ\s]{2,25}?(?:\s*:|\s+\d+\s+Vasilhas?|\s+1\s+p[eé]|\s+[Tt]em\b))",
            r"\1\n",
            text,
        )

        cleaned_lines: list[str] = []
        for raw_line in text.splitlines():
            cl = cls.clean_line(raw_line)
            if cl:
                cleaned_lines.append(cl)
        return cleaned_lines

    @classmethod
    def is_valid_stock_report_message(cls, raw_message: str) -> bool:
        """
        Verifica se a mensagem segue o PADRÃO OFICIAL de relatório de estoque
        (Pizzaria por seção, Embalagens/Sorvetes estruturado, ou Relação Produtos DiParma).
        Somente mensagens que retornam `True` aqui podem ADICIONAR novos produtos ao banco.
        """
        if not raw_message or len(raw_message.strip()) < 10:
            return False

        parsed = cls.parse_message(raw_message)
        return parsed.is_standard_pattern

    @classmethod
    def match_section_header(cls, line: str) -> tuple[str | None, str | None]:
        """
        Verifica se a linha é um cabeçalho de seção ou sub-cabeçalho.
        Retorna `(section_name, subsection_tag)`.
        """
        stripped = line.rstrip(":").strip()
        norm = FuzzyService.normalize_text(stripped)
        if not norm:
            return None, None

        if norm in KNOWN_SUBSECTION_HEADERS:
            return KNOWN_SUBSECTION_HEADERS[norm]

        if norm in KNOWN_SECTION_HEADERS:
            return KNOWN_SECTION_HEADERS[norm], None

        return None, None

    @classmethod
    def extract_numeric_and_unit(cls, raw_value: str) -> tuple[Decimal | None, str | None]:
        """Extrai quantidade numérica e unidade normalizada a partir do valor textual."""
        if not raw_value:
            return None, None

        cleaned = raw_value.strip()

        # Caso "<N> [unidade] e Meio/Meia" (ex: "3 Pct e Meio" -> 3.5, "01 e Meia" -> 1.5)
        num_e_meio = re.search(
            rf"(\d+)\s*({UNIT_TOKENS_REGEX})?\s+e\s+mei[oa]\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        if num_e_meio:
            base_num = Decimal(num_e_meio.group(1)) + Decimal("0.5")
            raw_u = num_e_meio.group(2)
            norm_u = FuzzyService.normalize_unit(raw_u) if raw_u else None
            return base_num, norm_u

        # Caso apenas "Meia vasilha" / "1/2 caixa" (sem número inteiro antes) -> 0.5
        if re.search(r"\b1/2\b|\bmei[oa]\b", cleaned, flags=re.IGNORECASE):
            unit_match = re.search(
                rf"\b({UNIT_TOKENS_REGEX})\b",
                cleaned,
                flags=re.IGNORECASE,
            )
            unit = FuzzyService.normalize_unit(unit_match.group(1)) if unit_match else None
            return Decimal("0.5"), unit

        match = NUMERIC_UNIT_EXTRACT_PATTERN.search(cleaned)
        if not match:
            return None, None

        num_str = match.group("num").replace(",", ".")
        try:
            num_val = Decimal(num_str)
        except InvalidOperation:
            num_val = None

        raw_unit = match.group("unit")
        norm_unit = FuzzyService.normalize_unit(raw_unit) if raw_unit else None
        return num_val, norm_unit

    @classmethod
    def _try_parse_sub_attribute_line(cls, line: str) -> tuple[str, str, bool] | None:
        """
        Verifica se a linha representa um sub-atributo do produto pai imediatamente anterior.
        Retorna `(attr_key, attr_value, is_incomplete)` ou `None` se não for sub-atributo.
        """
        dangling_colon = line.endswith(":")

        # 0. Padrão "<peso> porção: <qtd>" (ex: "150 porção: 00", "100 porca : 00")
        wf_match = WEIGHT_FIRST_PORTION_PATTERN.match(line.strip())
        if wf_match:
            weight = wf_match.group("weight")
            if not weight.lower().endswith("g"):
                weight = f"{weight}g"
            qty = wf_match.group("qty").strip()
            return ("porcoes", f"{qty} Porções de {weight}", False)

        # 1. Linha iniciando com quantidade + porções/panelas/vasilhas/peças
        qty_match = QUANTITY_SUBLINE_PATTERN.match(line)
        if qty_match:
            kind_raw = qty_match.group("kind")
            kind_norm = FuzzyService.remove_accents(kind_raw.lower())
            rest = qty_match.group("rest").strip()
            full_val = FuzzyService.normalize_inline_terms(line.rstrip(":").strip())
            # Ex: "02 peças:" possui quantidade completa antes dos dois-pontos, não é truncamento
            is_inc = False if kind_norm.startswith("peca") else (dangling_colon and (not rest or rest == ":"))

            if kind_norm.startswith("porc"):
                return ("porcoes", full_val, is_inc)
            if kind_norm.startswith("panela"):
                return ("panelas", full_val, is_inc)
            if kind_norm.startswith("vasilha"):
                return ("vasilhas", full_val, is_inc)
            if kind_norm.startswith("peca"):
                return ("peca", full_val, is_inc)
            if kind_norm.startswith("penca"):
                return ("pencas", full_val, is_inc)
            if kind_norm.startswith("abert"):
                return ("aberto", full_val, is_inc)
            if kind_norm.startswith("fechad"):
                return ("fechado", full_val, is_inc)
            if kind_norm.startswith("cozid"):
                return ("cozido", full_val, is_inc)
            if kind_norm.startswith("congelad"):
                return ("congelado", full_val, is_inc)
            if kind_norm.startswith("ralad"):
                return ("ralado", full_val, is_inc)
            if kind_norm.startswith("cortad") or kind_norm.startswith("fatiad"):
                return ("cortado", full_val, is_inc)

        # 2. Linha iniciando com verbo de ação/reposição (ex: "Trazer uma de Piaçaba", "Comprar", "Fazer")
        norm_line = FuzzyService.remove_accents(line.lower()).strip()
        if re.match(r"^(?:fazer|trazer|comprar|cortar|porcionar|temperar|precisa|repor)\b", norm_line) and ":" not in line:
            return ("acao", line.strip(), False)

        # 3. Linha iniciando com palavra-chave de estado secundário (ex: "Aberto: Sim", "Porções: 25 de 100g")
        for kw, attr_key in SUB_ATTRIBUTE_KEYWORDS.items():
            pattern = rf"^{re.escape(kw)}\b(?:\s*[:\-]\s*|\s+)(?P<val>.*)$"
            m = re.match(pattern, norm_line, flags=re.IGNORECASE)
            if m:
                if ":" in line:
                    left_part, right_part = line.split(":", 1)
                    left_norm = FuzzyService.remove_accents(left_part.lower()).strip()
                    if left_norm == kw:
                        raw_val = right_part
                    else:
                        raw_val = f"{right_part.strip()} ({left_part.strip()})" if right_part.strip() else ""
                else:
                    raw_val = re.sub(r"^\S+(?:\s+uso)?\s*", "", line, count=1)

                val_clean = FuzzyService.normalize_inline_terms(raw_val.strip())
                if not val_clean or dangling_colon:
                    return (attr_key, val_clean.rstrip(":").strip(), True)
                return (attr_key, val_clean, False)

            if norm_line.rstrip(":") == kw and dangling_colon:
                return (attr_key, "", True)

        return None

    @classmethod
    def _attach_sub_attribute(
        cls,
        product: ParsedProductItem,
        attr_key: str,
        attr_val: str,
        is_incomplete: bool,
    ) -> None:
        """Anexa um sub-atributo ao produto pai, tratando casos como Salmão (02 peças:), Palmito (Fechado: 01) e Vassoura (? / Trazer...)."""
        if not product.raw_main_value and attr_key in ("peca", "fechado") and attr_val:
            product.raw_main_value = attr_val if attr_key == "peca" else f"{attr_val} fechado"
            num_q, unit_q = cls.extract_numeric_and_unit(product.raw_main_value)
            product.numeric_quantity = num_q
            product.unit = unit_q
            if not is_incomplete:
                product.is_incomplete_data = False

        if attr_key == "acao" and attr_val and product.raw_main_value in ("", "?"):
            product.raw_main_value = attr_val
            product.is_incomplete_data = False

        if is_incomplete:
            product.is_incomplete_data = True

        if attr_key == "porcoes":
            existing = product.sub_attributes.get("porcoes")
            if isinstance(existing, list):
                if attr_val and attr_val not in existing:
                    existing.append(attr_val)
            elif isinstance(existing, str) and existing:
                product.sub_attributes["porcoes"] = [existing, attr_val] if attr_val else [existing]
            else:
                product.sub_attributes["porcoes"] = [attr_val] if attr_val else []
            if attr_val and not is_incomplete:
                if not product.raw_main_value:
                    product.raw_main_value = "00"
                    product.numeric_quantity = Decimal("0")
                if "peca" not in product.sub_attributes or len(product.sub_attributes.get("porcoes", [])) > 0:
                    product.is_incomplete_data = False
        else:
            existing = product.sub_attributes.get(attr_key)
            if existing and attr_val:
                product.sub_attributes[attr_key] = f"{existing} | {attr_val}"
            else:
                product.sub_attributes[attr_key] = attr_val

    @classmethod
    def _is_standalone_value_line(cls, line: str) -> bool:
        if ":" in line:
            return False
        return bool(STANDALONE_VALUE_LINE_PATTERN.match(line.strip()))

    @classmethod
    def parse_message(
        cls,
        raw_message: str,
        default_section: str | None = None,
    ) -> ParsedMessageResult:
        """
        Executa a máquina de estados sobre a mensagem do WhatsApp:
        1. Se for `RELAÇÃO PRODUTOS DIPARMA` (Comida Italiana), usa o parser especializado de blocos `▶️`/`➡️`.
        2. Caso contrário, processa linhas lógicas do padrão Pizzaria / mensagens avulsas.
        3. Determina `is_standard_pattern` (True somente se seguir o modelo oficial de relatório).
        """
        if not raw_message or not raw_message.strip():
            return ParsedMessageResult()

        # Ignora links puros
        if re.match(r"^https?://\S+$", raw_message.strip(), flags=re.IGNORECASE):
            return ParsedMessageResult()

        if cls._is_diparma_message(raw_message):
            parsed_diparma = cls._parse_diparma_message(raw_message)
            parsed_diparma.is_standard_pattern = len(parsed_diparma.items) >= 2
            return parsed_diparma

        result = ParsedMessageResult(report_origin="PIZZARIA")
        current_section: str | None = default_section
        current_subsection_tag: str | None = None
        has_explicit_section_header = bool(default_section)
        if current_section and current_section not in result.detected_sections:
            result.detected_sections.append(current_section)

        cleaned_lines = cls._split_into_logical_lines(raw_message)

        last_product: ParsedProductItem | None = None
        colon_structured_count = 0
        i = 0
        n = len(cleaned_lines)

        while i < n:
            line = cleaned_lines[i]

            # Ignora URLs no meio do texto
            if re.match(r"^https?://\S+$", line, flags=re.IGNORECASE):
                i += 1
                continue

            # 1. Verifica se é cabeçalho de seção ou sub-cabeçalho
            sec_header, sub_tag = cls.match_section_header(line)
            if sec_header:
                has_explicit_section_header = True
                current_section = sec_header
                current_subsection_tag = sub_tag
                if sec_header not in result.detected_sections:
                    result.detected_sections.append(sec_header)
                last_product = None
                i += 1
                continue

            # 2. Se já existe um produto anterior, verifica se a linha atual é valor quebrado ou sub-atributo
            if last_product is not None:
                if last_product.raw_main_value in ("", "?") and cls._is_standalone_value_line(line):
                    val_clean = FuzzyService.normalize_inline_terms(line)
                    last_product.raw_main_value = val_clean
                    num_q, unit_q = cls.extract_numeric_and_unit(val_clean)
                    last_product.numeric_quantity = num_q
                    last_product.unit = unit_q
                    last_product.is_incomplete_data = False
                    i += 1
                    continue

                sub_attr = cls._try_parse_sub_attribute_line(line)
                if sub_attr is not None:
                    attr_key, attr_val, is_inc = sub_attr
                    cls._attach_sub_attribute(last_product, attr_key, attr_val, is_inc)
                    i += 1
                    continue

            # 3. Interpreta a linha como um novo Produto com dois-pontos (:)
            if ":" in line:
                name_part, val_part = line.split(":", 1)
                raw_name = name_part.strip(" :-•●*")
                raw_val = FuzzyService.normalize_inline_terms(val_part.strip())

                if not raw_name or raw_name.lower() in ("http", "https"):
                    result.unrecognized_lines.append(line)
                    i += 1
                    continue

                colon_structured_count += 1
                if raw_val == "?":
                    raw_val = ""
                    is_incomplete = True
                else:
                    is_incomplete = not bool(raw_val)

                num_q, unit_q = cls.extract_numeric_and_unit(raw_val)
                item = ParsedProductItem(
                    raw_name=raw_name,
                    canonical_candidate=FuzzyService.canonicalize_display_name(raw_name),
                    normalized_name=FuzzyService.normalize_text(raw_name),
                    raw_main_value=raw_val,
                    numeric_quantity=num_q,
                    unit=unit_q,
                    sub_attributes={"subcategoria": current_subsection_tag} if current_subsection_tag else {},
                    section_name=current_section,
                    is_incomplete_data=is_incomplete,
                    report_origin="PIZZARIA",
                )
                result.items.append(item)
                last_product = item
                i += 1
                continue

            # 4. Mensagem solta estilo "Acabou limão" / "Trazer cebola grande" (só quando sem cabeçalho de relatório)
            if not has_explicit_section_header:
                act_match = ACTION_PREFIX_ITEM_PATTERN.match(line)
                if act_match:
                    raw_name = act_match.group("name").strip(" :-•●*")
                    action_word = act_match.group("action").strip().capitalize()
                    item = ParsedProductItem(
                        raw_name=raw_name,
                        canonical_candidate=FuzzyService.canonicalize_display_name(raw_name),
                        normalized_name=FuzzyService.normalize_text(raw_name),
                        raw_main_value="Trazer" if action_word.lower().startswith("precisa") else action_word,
                        numeric_quantity=Decimal("0"),
                        unit=None,
                        sub_attributes={},
                        section_name=current_section,
                        is_incomplete_data=False,
                        report_origin="LOOSE",
                    )
                    result.items.append(item)
                    last_product = item
                    i += 1
                    continue

            # 5. Linha SEM dois-pontos com valor no final (ex: "Frango 15kg", "Laranja 4L", "Tomate grande tem")
            inline_match = INLINE_SUFFIX_VALUE_PATTERN.match(line)
            if inline_match:
                raw_name = inline_match.group("name").strip(" :-•●*")
                raw_val = FuzzyService.normalize_inline_terms(inline_match.group("value").strip())
                num_q, unit_q = cls.extract_numeric_and_unit(raw_val)
                item = ParsedProductItem(
                    raw_name=raw_name,
                    canonical_candidate=FuzzyService.canonicalize_display_name(raw_name),
                    normalized_name=FuzzyService.normalize_text(raw_name),
                    raw_main_value=raw_val,
                    numeric_quantity=num_q,
                    unit=unit_q,
                    sub_attributes={"subcategoria": current_subsection_tag} if current_subsection_tag else {},
                    section_name=current_section,
                    is_incomplete_data=False,
                    report_origin="PIZZARIA",
                )
                result.items.append(item)
                last_product = item
                i += 1
                continue

            # 6. Linha com apenas o nome do produto (aguardando valor na linha seguinte, ex: "Leite condensado zero lactose\n06 uni")
            if re.match(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-\(\)&]+$", line):
                # Só aceita nome sem valor se houver uma próxima linha que seja valor ou sub-atributo!
                has_followup = False
                if i + 1 < n:
                    next_line = cleaned_lines[i + 1]
                    if cls._is_standalone_value_line(next_line) or cls._try_parse_sub_attribute_line(next_line) is not None:
                        has_followup = True

                if has_followup:
                    raw_name = line.strip(" :-•●*")
                    item = ParsedProductItem(
                        raw_name=raw_name,
                        canonical_candidate=FuzzyService.canonicalize_display_name(raw_name),
                        normalized_name=FuzzyService.normalize_text(raw_name),
                        raw_main_value="",
                        numeric_quantity=None,
                        unit=None,
                        sub_attributes={"subcategoria": current_subsection_tag} if current_subsection_tag else {},
                        section_name=current_section,
                        is_incomplete_data=True,
                        report_origin="PIZZARIA",
                    )
                    result.items.append(item)
                    last_product = item
                    i += 1
                    continue

            result.unrecognized_lines.append(line)
            i += 1

        # Deduplicação por (section_name, normalized_name) preservando a última ocorrência (a mais atual)
        dedup_map: dict[tuple[str | None, str], ParsedProductItem] = {}
        for item in result.items:
            if not item.raw_main_value:
                useful_subs = {
                    k: v for k, v in item.sub_attributes.items() if k != "subcategoria" and v
                }
                if not useful_subs:
                    item.is_incomplete_data = True
            key = (item.section_name, item.normalized_name)
            if key in dedup_map:
                del dedup_map[key]
            dedup_map[key] = item

        result.items = list(dedup_map.values())

        # Classifica se a mensagem está no PADRÃO DE MENSAGEM PADRÃO:
        # 1) Possui cabeçalho oficial de seção E >= 2 itens válidos; OU
        # 2) É o relatório estruturado de Embalagens/Preparos sem cabeçalho no topo (>= 3 linhas "Item: Valor")
        valid_valued_items = [
            it for it in result.items if it.raw_main_value or any(k != "subcategoria" for k in it.sub_attributes)
        ]
        if has_explicit_section_header and len(valid_valued_items) >= 2:
            result.is_standard_pattern = True
        elif colon_structured_count >= 3 and len(valid_valued_items) >= 3:
            result.is_standard_pattern = True
        else:
            result.is_standard_pattern = False
            result.report_origin = "LOOSE"

        return result
