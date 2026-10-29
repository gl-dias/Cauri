"""Transcrição de voz atrás de uma interface.

A implementação é o Whisper pela API da Groq. Sem ``GROQ_API_KEY``, a API diz que não há
transcrição no servidor e o front usa a Web Speech API do navegador. O áudio não é
guardado: vai para a Groq e volta como texto, que o usuário revisa antes de enviar.
"""

from __future__ import annotations

from typing import Protocol

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
# Uns 2 minutos de fala em webm/opus; o front para de gravar sozinho aos 30 segundos.
MAX_AUDIO_BYTES = 2 * 1024 * 1024


class TranscriptionError(Exception):
    """Falha ao transcrever, com mensagem para a tela."""


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str: ...


class GroqTranscriber:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        client: httpx.Client | None = None,
        url: str = GROQ_URL,
    ) -> None:
        self._key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=60)
        self._url = url

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        if not audio:
            raise TranscriptionError("Áudio vazio.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise TranscriptionError("Áudio longo demais. Fale uma operação por vez.")
        try:
            response = self._client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                data={"model": self._model, "language": "pt", "response_format": "json"},
                files={"file": (filename, audio, content_type)},
            )
        except httpx.HTTPError as exc:
            raise TranscriptionError("A transcrição não respondeu. Tente de novo.") from exc
        if response.status_code >= 400:
            raise TranscriptionError("A transcrição não respondeu. Tente de novo.")
        text = str(response.json().get("text", "")).strip()
        if not text:
            raise TranscriptionError("Não entendi o áudio. Tente de novo, mais perto do microfone.")
        return text
