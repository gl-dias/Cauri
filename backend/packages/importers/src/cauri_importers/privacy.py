"""Proteção de dados pessoais na importação.

A regra principal está no leitor de planilha: ele só carrega as colunas que o
adaptador declara, então CPF, nome e qualquer outra coluna do arquivo nunca entram na
memória do resto do sistema. Aqui ficam as defesas extras para os textos que entram:
nada que pareça CPF sai do parser, nem em texto livre.
"""

from __future__ import annotations

import re
import unicodedata

# CPF com hífen (123.456.789-00 ou 123456789-00), ou 11 dígitos ou mais seguidos que não
# são parte de um número decimal: "100.00000000USDT" e "0,00012345678901" não são CPF.
_CPF = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-\d{2}")
_LONG_DIGITS = re.compile(r"(?<![\d.,])\d{11,}(?![\d.,]*\d)")
MASK = "***"


def scrub(text: str) -> str:
    """Troca por ``***`` qualquer coisa com cara de CPF (formatado ou só dígitos)."""
    return _LONG_DIGITS.sub(MASK, _CPF.sub(MASK, text))


def looks_like_cpf(text: str) -> bool:
    return bool(_CPF.search(text) or _LONG_DIGITS.search(text))


def normalize(text: str) -> str:
    """Minúsculas, sem acento e com espaços simples, para comparar cabeçalhos e rótulos."""
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(stripped.lower().split())
