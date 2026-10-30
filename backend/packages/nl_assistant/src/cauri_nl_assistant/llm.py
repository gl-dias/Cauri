"""Extração pela API da Anthropic (Haiku), com saída estruturada por ferramenta obrigatória.

O pedido leva só o que o usuário escreveu (a frase e, com cartão aberto, as frases
anteriores da conversa) e a data de hoje. Nada da carteira, nada de ticker que o usuário
tenha: o modelo devolve o que foi falado e o Python resolve o resto.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import httpx

from cauri_nl_assistant.extraction import (
    SYSTEM,
    TOOL,
    TOOL_NAME,
    Complement,
    Extraction,
    ExtractionError,
    SpokenOp,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-5-5"
_RETRY_STATUS = {429, 500, 502, 503, 529}


class AnthropicExtractor:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        client: httpx.Client | None = None,
        url: str = API_URL,
    ) -> None:
        self._key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=30)
        self._url = url

    @property
    def model(self) -> str:
        return self._model

    def request_body(self, text: str, today: date, context: Sequence[str] = ()) -> dict[str, Any]:
        return {
            "model": self._model,
            "max_tokens": 1024,
            "system": SYSTEM.format(tool=TOOL_NAME, today=today.isoformat()),
            "messages": [{"role": "user", "content": user_content(text, context)}],
            "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }

    def extract(self, text: str, today: date, context: Sequence[str] = ()) -> Extraction:
        body = self.request_body(text, today, context)
        headers = {
            "x-api-key": self._key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        response: httpx.Response | None = None
        for _ in range(2):  # uma nova tentativa em sobrecarga ou limite; nunca insiste
            try:
                response = self._client.post(self._url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                raise ExtractionError("O assistente não respondeu agora. Tente de novo.") from exc
            if response.status_code not in _RETRY_STATUS:
                break
        assert response is not None
        if response.status_code >= 400:
            raise ExtractionError("O assistente não respondeu agora. Tente de novo.")
        return parse_response(response.json(), self._model)


def user_content(text: str, context: Sequence[str]) -> str:
    """A frase sozinha; com cartão aberto, antes dela as frases anteriores do usuário."""
    if not context:
        return text
    before = "\n".join(f"- {c}" for c in context)
    return (
        "Frases anteriores desta conversa (o cartão continua aberto):\n"
        f"{before}\n\nFrase nova: {text}"
    )


def parse_response(data: dict[str, Any], model: str) -> Extraction:
    blocks = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
    if not blocks:
        raise ExtractionError("Não entendi a frase. Tente de novo com outras palavras.")
    tool_input = blocks[0].get("input") or {}
    raw_ops = tool_input.get("operacoes", [])
    if not isinstance(raw_ops, list):
        raise ExtractionError("Não entendi a frase. Tente de novo com outras palavras.")
    ops = tuple(
        op
        for op in (SpokenOp.from_json(o) for o in raw_ops if isinstance(o, dict))
        if op.ativo or op.tipo == "outro"
    )
    usage = data.get("usage") or {}
    return Extraction(
        ops=ops,
        model=model,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        complement=None if ops else Complement.from_json(tool_input.get("complemento")),
    )
