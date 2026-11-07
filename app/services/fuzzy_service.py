import re
import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING

from rapidfuzz import fuzz, process

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.product import Product


# Dicionário de normalização de unidades e termos de sub-atributos
UNIT_NORMALIZATION_MAP: dict[str, str] = {
    "porca": "porcoes",
    "porcao": "porcoes",
    "porção": "porcoes",
    "porcoes": "porcoes",
    "porções": "porcoes",
    "porc": "porcoes",
    "uni": "unidades",
    "umi": "unidades",
    "unid": "unidades",
    "und": "unidades",
    "unidade": "unidades",
    "unidades": "unidades",
    "pct": "pacotes",
    "pcts": "pacotes",
    "pacote": "pacotes",
    "pacotes": "pacotes",
    "cx": "caixas",
    "cxs": "caixas",
    "caixa": "caixas",
    "caixas": "caixas",
    "kg": "kg",
    "kgs": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "quilo": "kg",
    "quilos": "kg",
    "g": "g",
    "gr": "g",
    "grs": "g",
    "gm": "g",
    "gms": "g",
    "grama": "g",
    "gramas": "g",
    "l": "L",
    "lt": "L",
    "lts": "L",
    "litro": "L",
    "litros": "L",
    "ml": "ml",
    "vasilha": "vasilhas",
    "vasilhas": "vasilhas",
    "vas": "vasilhas",
    "panela": "panelas",
    "panelas": "panelas",
    "barra": "barras",
    "barras": "barras",
    "barrinha": "barrinhas",
    "barrinhas": "barrinhas",
    "penca": "pencas",
    "pencas": "pencas",
    "saco": "sacos",
    "sacos": "sacos",
    "sc": "sacos",
    "balde": "baldes",
    "baldes": "baldes",
    "fardo": "fardos",
    "fardos": "fardos",
    "garrafa": "garrafas",
    "garrafas": "garrafas",
    "grf": "garrafas",
    "lata": "latas",
    "latas": "latas",
    "peca": "pecas",
    "peça": "pecas",
    "pecas": "pecas",
    "peças": "pecas",
    "pc": "pecas",
    "pcs": "pecas",
    "pçs": "pecas",
    "pe": "pes",
    "pé": "pes",
    "pes": "pes",
    "pés": "pes",
    "placa": "placas",
    "placas": "placas",
    "rodela": "rodelas",
    "rodelas": "rodelas",
    "fatia": "fatias",
    "fatias": "fatias",
    "caixote": "caixotes",
    "caixotes": "caixotes",
    "bandeja": "bandejas",
    "bandejas": "bandejas",
    "pote": "potes",
    "potes": "potes",
    "bisnaga": "bisnagas",
    "bisnagas": "bisnagas",
    "galao": "galoes",
    "galão": "galoes",
    "galoes": "galoes",
    "galões": "galoes",
    "rolo": "rolos",
    "rolos": "rolos",
}

# Correções ortográficas aplicadas por expressão / palavra
KNOWN_SPELLING_CORRECTIONS: dict[str, str] = {
    "cifff": "cif",
    "ciff": "cif",
    "creme cheese": "cream cheese",
    "creem cheese": "cream cheese",
    "cream chesse": "cream cheese",
    "cream chese": "cream cheese",
    "catupiri": "catupiry",
    "mucarela": "mussarela",
    "muçarela": "mussarela",
    "mozarela": "mussarela",
    "calabreza": "calabresa",
    "kinor": "knorr",
    "requeijao catupiri": "requeijao catupiry",
    "caixas quadrada da pequena": "caixa quadrada pequena",
    "caixas quadrada pequena": "caixa quadrada pequena",
    "caixas quadrada grande": "caixa quadrada grande",
    "caixas super fatia": "caixa super fatia",
    "caixas oitavada grande": "caixa oitavada grande",
    "caixas oitavada pequena": "caixa oitavada pequena",
}

# Unificação exata de nomes equivalentes entre Pizzaria e Comida Italiana (DiParma)
EXACT_PRODUCT_SYNONYMS: dict[str, str] = {
    "oleo soja": "oleo",
    "oleo de soja": "oleo",
    "alface": "alface verde",
    "arroz c brocolis": "arroz com brocolis",
    "knorr carne": "knorr de carne",
    "knorr frango": "knorr de frango",
}

# Nomes de exibição padronizados
CANONICAL_DISPLAY_NAMES: dict[str, str] = {
    "cif": "Cif",
    "cream cheese": "Cream Cheese",
    "mm": "M&M",
    "oleo": "Óleo",
    "acucar": "Açúcar",
    "brocolis": "Brócolis",
    "camarao": "Camarão",
    "salmao": "Salmão",
    "file mignon": "Filé Mignon",
    "carne moida": "Carne Moída",
    "alface verde": "Alface Verde",
    "arroz com brocolis": "Arroz com Brócolis",
    "knorr de frango": "Knorr de Frango",
    "knorr de carne": "Knorr de Carne",
    "leite liquido": "Leite Líquido",
    "farinha de rosca": "Farinha de Rosca",
    "molho sugo": "Molho Sugo",
    "molho branco": "Molho Branco",
    "molho tare": "Molho Tarê",
    "pao de hot dog": "Pão de Hot Dog",
    "sabao em po": "Sabão em Pó",
    "sabao de prato": "Sabão de Prato",
    "papel higienico": "Papel Higiênico",
    "papel toalha": "Papel Toalha",
    "parmesao": "Parmesão",
    "nhoque": "Nhoque",
}

# Grupos de qualificadores mutuamente exclusivos para evitar falso-positivo entre variações distintas
CONFLICTING_QUALIFIER_GROUPS: list[set[str]] = [
    {"grande", "pequena", "pequeno", "media", "medio", "broto", "familia", "gigante", "super"},
    {"seco", "cereja", "grande", "holandes"},
    {"fatiada", "fatiado", "ralada", "ralado", "inteira", "peca", "moida"},
    {"catupiry", "tirolez", "cheddar", "cremoso"},
    {"mussarela", "coalho", "parmesao", "gorgonzola", "cheddar", "prato", "reino", "ricota", "provolone"},
    {"sol", "seca", "moida", "hamburguer", "file", "costela", "costelinha", "picanha", "alcatra", "frango", "bacon", "calabresa", "carne"},
    {"prata", "terra", "nanica", "maca"},
    {"suco", "pizza", "polpa"},
    {"roxo", "roxa", "verde", "americana", "crespa"},
    {"preto", "branco", "dourado"},
    {"demerara", "mascavo", "cristal", "refinado"},
    {"leite", "culinario", "avela", "chantilly", "condensado", "liquido", "po", "ninho"},
    {"sugo", "tare", "barbecue", "shoyu", "pesto", "madeira", "branco", "queijo"},
    {"morango", "chocolate", "creme", "flocos", "napolitano", "baunilha", "limao", "maracuja", "abacaxi", "acerola", "goiaba", "caju", "caja", "graviola", "cupuacu", "manga", "ovomaltine", "pacoca"},
    {"quadrada", "oitavada", "redonda"},
    {"zero", "integral", "desnatado", "tradicional"},
    {"fettuccine", "penne", "espaguete", "nhoque", "lasanha"},
]


class FuzzyService:
    """Serviço de higienização textual, normalização de unidades e busca difusa (Fuzzy Matching)."""

    @staticmethod
    def remove_accents(text: str) -> str:
        """Remove acentos mantendo caracteres base ASCII."""
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """
        Normaliza o nome de um produto ou seção:
        1. Lowercase e remoção de acentos
        2. Redução de 3+ caracteres repetidos consecutivos (ex: 'cifff' -> 'cif')
        3. Preservação de 'm&m' e tratamento de 'c/' -> 'com'
        4. Aplicação de correções ortográficas e sinônimos entre Pizzaria e DiParma
        """
        if not text:
            return ""

        cleaned = cls.remove_accents(text.lower().strip())
        cleaned = cleaned.replace("m&m", "mm")
        cleaned = re.sub(r"\bc/\s*", "com ", cleaned)
        # Reduz 3 ou mais letras idênticas consecutivas para 1 (ex: cifff -> cif)
        cleaned = re.sub(r"([a-z])\1{2,}", r"\1", cleaned)
        # Substitui caracteres especiais por espaço (preservando letras e dígitos)
        cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        for wrong, right in KNOWN_SPELLING_CORRECTIONS.items():
            cleaned = re.sub(rf"\b{re.escape(wrong)}\b", right, cleaned)

        cleaned = re.sub(r"\bcaixas\b", "caixa", cleaned)
        cleaned = re.sub(r"\bcaixotes\b", "caixote", cleaned)
        cleaned = re.sub(r"\bda\s+(pequena|grande|media)\b", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if cleaned in EXACT_PRODUCT_SYNONYMS:
            cleaned = EXACT_PRODUCT_SYNONYMS[cleaned]

        return cleaned

    @classmethod
    def slugify(cls, text: str) -> str:
        """Gera um slug URL-safe a partir de um nome."""
        norm = cls.normalize_text(text)
        return re.sub(r"[^a-z0-9]+", "-", norm).strip("-")

    @classmethod
    def normalize_unit(cls, raw_unit: str | None) -> str | None:
        """Normaliza termos de unidade ou sub-atributos ('porca' -> 'porcoes', 'umi'/'uni' -> 'unidades')."""
        if not raw_unit:
            return None
        key = cls.remove_accents(raw_unit.lower().strip().rstrip("."))
        key = re.sub(r"([a-z])\1{2,}", r"\1", key)
        return UNIT_NORMALIZATION_MAP.get(key, raw_unit.strip().lower())

    @classmethod
    def normalize_inline_terms(cls, text: str) -> str:
        """
        Corrige erros de digitação frequentes dentro de valores/sub-atributos,
        como '100 porca' -> '100 porções', 'temm' -> 'Tem', '27 umi' -> '27 uni', 'O0' -> '00'.
        """
        if not text:
            return ""
        result = re.sub(r"\b[Oo](\d)", r"0\1", text)
        result = re.sub(r"\bporca\b", "porções", result, flags=re.IGNORECASE)
        result = re.sub(r"\bporcao\b", "porções", result, flags=re.IGNORECASE)
        result = re.sub(r"\bumi\b", "uni", result, flags=re.IGNORECASE)
        result = re.sub(r"\btem{2,}\b", "Tem", result, flags=re.IGNORECASE)
        return result.strip()

    @classmethod
    def canonicalize_display_name(cls, raw_name: str) -> str:
        """
        Formata um nome limpo e padronizado para exibição.
        Ex: 'cifff' -> 'Cif', 'OLEO SOJA' -> 'Óleo', 'KINOR DE FRANGO' -> 'Knorr de Frango'.
        """
        if raw_name.strip().upper() == "M&M":
            return "M&M"

        norm = cls.normalize_text(raw_name)
        if norm in CANONICAL_DISPLAY_NAMES:
            return CANONICAL_DISPLAY_NAMES[norm]

        cleaned = re.sub(r"([A-Za-zÀ-ÿ])\1{2,}", r"\1", raw_name.strip())
        cleaned = re.sub(r"\bc/\s*", "com ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" :-•●*▶➡")
        if cleaned.lower() in KNOWN_SPELLING_CORRECTIONS:
            corrected = KNOWN_SPELLING_CORRECTIONS[cleaned.lower()]
            return " ".join(
                w.capitalize() if w not in ("de", "da", "do", "dos", "das", "e", "em", "para", "com") else w
                for w in corrected.split()
            )

        words = cleaned.split()
        formatted: list[str] = []
        for idx, word in enumerate(words):
            lower_w = word.lower()
            if word.upper() == "M&M":
                formatted.append("M&M")
            elif idx > 0 and lower_w in ("de", "da", "do", "dos", "das", "e", "em", "para", "com", "no", "na"):
                formatted.append(lower_w)
            else:
                formatted.append(word[:1].upper() + word[1:].lower() if len(word) > 1 else word.upper())
        return " ".join(formatted)

    @classmethod
    def _has_conflicting_qualifiers(cls, norm_a: str, norm_b: str) -> bool:
        """
        Verifica se dois nomes possuem qualificadores mutuamente exclusivos
        (ex: 'calabresa fatiada' vs 'calabresa ralada', 'alho' vs 'alho frito', 'ovos' vs 'ovo de codorna').
        """
        tokens_a = set(norm_a.split())
        tokens_b = set(norm_b.split())

        strict_differentiators = {
            "zero",
            "lactose",
            "demerara",
            "cereja",
            "seco",
            "ralada",
            "ralado",
            "fatiada",
            "fatiado",
            "terra",
            "prata",
            "suco",
            "pizza",
            "roxo",
            "verde",
            "preto",
            "branco",
            "frito",
            "frita",
            "palha",
            "codorna",
            "liquido",
            "po",
            "condensado",
            "plastico",
            "biquinho",
            "risoto",
            "arroz",
            "pimenta",
            "boleadas",
            "boleada",
            "abertas",
            "aberta",
            "ninho",
            "panela",
            "prato",
            "higienico",
            "toalha",
            "super",
            "fatia",
        }
        diff_a = tokens_a.intersection(strict_differentiators)
        diff_b = tokens_b.intersection(strict_differentiators)
        if diff_a != diff_b:
            return True

        for group in CONFLICTING_QUALIFIER_GROUPS:
            found_a = tokens_a.intersection(group)
            found_b = tokens_b.intersection(group)
            if found_a and found_b and found_a != found_b:
                return True
        return False

    @classmethod
    def find_best_product_match(
        cls,
        raw_name: str,
        candidates: Sequence["Product"],
        threshold: int | None = None,
    ) -> tuple["Product | None", float]:
        """
        Compara o nome extraído com `canonical_name`, `normalized_name` e `aliases` de todos os
        produtos candidatos usando `rapidfuzz.process.extractOne`.
        """
        if not raw_name or not candidates:
            return None, 0.0

        min_score = threshold if threshold is not None else settings.FUZZY_MATCH_THRESHOLD
        query_norm = cls.normalize_text(raw_name)
        if not query_norm:
            return None, 0.0

        for product in candidates:
            prod_norm = cls.normalize_text(product.normalized_name or product.canonical_name)
            if query_norm == prod_norm:
                return product, 100.0
            for alias in product.aliases or []:
                if query_norm == cls.normalize_text(alias):
                    return product, 100.0

        choice_strings: list[str] = []
        choice_owners: list["Product"] = []

        for product in candidates:
            prod_norm = cls.normalize_text(product.normalized_name or product.canonical_name)
            if prod_norm and not cls._has_conflicting_qualifiers(query_norm, prod_norm):
                choice_strings.append(prod_norm)
                choice_owners.append(product)

            for alias in product.aliases or []:
                alias_norm = cls.normalize_text(alias)
                if alias_norm and not cls._has_conflicting_qualifiers(query_norm, alias_norm):
                    choice_strings.append(alias_norm)
                    choice_owners.append(product)

        if not choice_strings:
            return None, 0.0

        def _combined_scorer(s1: str, s2: str, **kwargs) -> float:
            tsr = fuzz.token_sort_ratio(s1, s2, **kwargs)
            wrat = fuzz.WRatio(s1, s2, **kwargs)
            if tsr < 75.0:
                return tsr
            return max(tsr, wrat)

        match_best = process.extractOne(
            query_norm,
            choice_strings,
            scorer=_combined_scorer,
        )

        if match_best is not None:
            _, best_score, best_idx = match_best
            if best_score >= min_score:
                return choice_owners[best_idx], round(float(best_score), 2)
            return None, round(float(best_score), 2)

        return None, 0.0
