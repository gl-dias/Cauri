"""De "como o arquivo escreve a corretora" para o id do cadastro.

Aceita o id (``xp``), o nome cadastrado (``XP Investimentos``) e a razão social que a
B3 usa na coluna Instituição (``XP INVESTIMENTOS CCTVM S/A``). A lista abaixo é de
trechos da razão social, testados em ordem: os mais específicos primeiro, porque
"CLEAR CORRETORA - GRUPO XP" também tem "XP".
"""

from __future__ import annotations

from collections.abc import Mapping

from cauri_importers.privacy import normalize

_LEGAL_NAMES: tuple[tuple[str, str], ...] = (
    ("clear corretora", "clear"),
    ("rico investimentos", "rico"),
    ("rico corretora", "rico"),
    ("xp investimentos", "xp"),
    ("btg pactual", "btg"),
    ("nu invest", "nubank"),
    ("nubank", "nubank"),
    ("easynvest", "nubank"),
    ("inter distribuidora", "inter"),
    ("banco inter", "inter"),
    ("inter dtvm", "inter"),
    ("genial", "genial"),
    ("toro ", "toro"),
    ("agora ", "agora"),
    ("c6 ctvm", "c6"),
    ("c6 bank", "c6"),
    ("itau", "itau"),
    ("bradesco", "bradesco"),
    ("santander", "santander"),
    ("bb banco de investimento", "bb"),
    ("banco do brasil", "bb"),
    ("caixa economica", "caixa"),
)


def resolve(text: str, brokers: Mapping[str, str]) -> str | None:
    """Id da corretora cadastrada, ou ``None`` se não der para saber com segurança."""
    norm = normalize(text)
    if norm in brokers:
        return norm
    by_name = {normalize(name): broker_id for broker_id, name in brokers.items()}
    if norm in by_name:
        return by_name[norm]
    padded = f"{norm} "
    for fragment, broker_id in _LEGAL_NAMES:
        if fragment in padded and broker_id in brokers:
            return broker_id
    return None
