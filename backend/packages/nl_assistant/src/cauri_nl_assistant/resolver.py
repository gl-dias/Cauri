"""Do ativo como falado para o ticker, em Python determinístico.

1. Ticker escrito (PETR4, HGLG11, BTC, TD-SELIC-01032029) vale direto, se existir.
2. Apelido (petrobras, itau, bitcoin) aponta para um emissor ou para um ativo. Empresas
   nunca se misturam: "itau" é ITUB e "itausa" é ITSA, cada um com o seu apelido.
3. Emissor com mais de um ticker (PETR3 e PETR4): se o usuário tem só um deles, usa esse;
   se tem os dois, ou nenhum, pergunta.
4. "Tesouro selic 2029" pelo nome do título no cadastro.

Sem fuzzy silencioso: o que não bate exatamente vira pergunta.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from cauri_core import AssetClass
from cauri_ledger import CatalogAsset, Ledger

_TICKER = re.compile(r"^[A-Z0-9]{2,12}$|^TD-[A-Z-]+-\d{8}$")
_BROKER_PREFIX = re.compile(r"^(?:na|no|pela|pelo)\s+")
_BROKER_FILLER = frozenset({"banco", "bank", "investimentos", "do", "da", "de"})


@dataclass(frozen=True, slots=True)
class Resolved:
    ticker: str
    asset_class: AssetClass
    name: str


@dataclass(frozen=True, slots=True)
class Ask:
    text: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NotFound:
    text: str


Resolution = Resolved | Ask | NotFound


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(stripped.lower().split())


def match_broker(brokers: Mapping[str, str], spoken: str) -> str | None:
    """Corretora como falada ("xp", "na inter", "banco do brasil") para o id, se só uma bate.

    Vale o id ou o nome inteiro; senão, uma palavra própria do nome ("pactual" é o BTG).
    """
    norm = _BROKER_PREFIX.sub("", normalize(spoken))
    if not norm:
        return None
    exact = [b for b, name in brokers.items() if norm in (normalize(b), normalize(name))]
    if exact:
        return exact[0] if len(exact) == 1 else None
    by_word = [
        b for b, name in brokers.items() if norm in set(normalize(name).split()) - _BROKER_FILLER
    ]
    return by_word[0] if len(by_word) == 1 else None


class Resolver:
    def __init__(self, ledger: Ledger, user_id: UUID) -> None:
        self._ledger = ledger
        self._user = user_id

    def resolve(self, spoken: str) -> Resolution:
        text = spoken.strip()
        if not text:
            return NotFound("Faltou o ativo.")
        norm = normalize(text)
        code = text.upper().replace(" ", "")

        if norm.startswith("tesouro "):
            return self._tesouro(text, norm)

        alias = self._ledger.alias(norm)
        if alias is not None:
            kind, target = alias
            if kind == "asset":
                return self._direct(target) or NotFound(f'Não achei "{text}" no cadastro.')
            return self._issuer(target, text)

        if _TICKER.match(code):
            found = self._direct(code)
            if found is not None:
                return found
            return NotFound(f"Não achei o ticker {code} no cadastro. Confira e diga de novo.")
        return NotFound(f'Não reconheci "{text}". Diga o ticker (ex.: PETR4, BTC).')

    def _direct(self, ticker: str) -> Resolved | None:
        asset = self._ledger.assets({ticker}).get(ticker)
        return _resolved(asset) if asset else None

    def _issuer(self, issuer: str, spoken: str) -> Resolution:
        candidates = [
            a
            for a in self._ledger.issuer_assets(issuer)
            if a.asset_class in {AssetClass.ACAO, AssetClass.FII}
        ]
        if not candidates:
            return NotFound(f'Não achei ativos de "{spoken}" no cadastro.')
        tickers = [a.ticker for a in candidates]
        held = sorted(self._ledger.holdings(self._user, tickers))
        if len(held) == 1:
            return _resolved(next(a for a in candidates if a.ticker == held[0]))
        if len(held) > 1:
            return Ask(f"Você tem {_join(held)}. Qual delas?", tuple(held))
        if len(candidates) == 1:
            return _resolved(candidates[0])  # sem ambiguidade: a empresa só tem um ticker
        return Ask(f'Qual ticker de "{spoken}"?', tuple(tickers))

    def _tesouro(self, spoken: str, norm: str) -> Resolution:
        titles = self._ledger.tesouro_titles()
        matches = [
            t
            for t in titles
            if normalize(t.name) == norm or normalize(t.name).startswith(f"{norm} (")
        ]
        if len(matches) == 1:
            return _resolved(matches[0])
        if matches:
            return Ask(f'Qual título de "{spoken}"?', tuple(t.ticker for t in matches))
        return NotFound(f'Não achei o título "{spoken}" no cadastro do Tesouro.')


def _resolved(asset: CatalogAsset) -> Resolved:
    return Resolved(asset.ticker, asset.asset_class, asset.name)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} e {items[-1]}"
