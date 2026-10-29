"""Proteção de dados pessoais na importação.

A regra principal está no leitor de planilha: ele só carrega as colunas que o
adaptador declara, então CPF, nome e qualquer outra coluna do arquivo nunca entram na
memória do resto do sistema. Aqui ficam as defesas extras para os textos que entram:
nada que pareça CPF sai do parser, nem em texto livre.
"""

from __future__ import annotations

import re
import unicodedata

_CPF = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")
_LONG_DIGITS = re.compile(r"\d{11,}")
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
