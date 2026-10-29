/**
 * Voz: grava no navegador e transcreve no servidor (Whisper pela Groq); sem chave no
 * servidor, usa a Web Speech API do próprio navegador. O texto volta para o campo, e o
 * usuário revisa antes de enviar.
 */
import { useCallback, useRef, useState } from "react";

type Recognition = {
  lang: string;
  interimResults: boolean;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type RecognitionCtor = new () => Recognition;

function browserRecognition(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useVoice(mode: "groq" | "navegador" | undefined, transcribe: (audio: Blob) => Promise<string>, onText: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const recognition = useRef<Recognition | null>(null);

  const supported =
    mode === "groq"
      ? typeof navigator !== "undefined" && Boolean(navigator.mediaDevices) && typeof MediaRecorder !== "undefined"
      : mode === "navegador" && typeof window !== "undefined" && browserRecognition() !== null;

  const start = useCallback(async () => {
    setError(null);
    if (mode === "groq") {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const chunks: Blob[] = [];
        const rec = new MediaRecorder(stream);
        rec.ondataavailable = (e) => chunks.push(e.data);
        rec.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          setBusy(true);
          try {
            onText(await transcribe(new Blob(chunks, { type: rec.mimeType || "audio/webm" })));
          } catch {
            setError("Não consegui transcrever. Tente de novo ou digite.");
          } finally {
            setBusy(false);
          }
        };
        recorder.current = rec;
        rec.start();
        setListening(true);
      } catch {
        setError("Sem acesso ao microfone.");
      }
      return;
    }
    const Ctor = browserRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "pt-BR";
    rec.interimResults = false;
    rec.onresult = (event) => {
      const text = Array.from(event.results)
        .map((r) => r[0]?.transcript ?? "")
        .join(" ")
        .trim();
      if (text) onText(text);
    };
    rec.onerror = () => setError("Não entendi o áudio. Tente de novo ou digite.");
    rec.onend = () => setListening(false);
    recognition.current = rec;
    rec.start();
    setListening(true);
  }, [mode, onText, transcribe]);

  const stop = useCallback(() => {
    recorder.current?.stop();
    recognition.current?.stop();
    recorder.current = null;
    recognition.current = null;
    setListening(false);
  }, []);

  return { supported, listening, busy, error, start, stop };
}
