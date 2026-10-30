import { ArrowRight, Mail } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { PrimaryButton } from "@/ui/controls";
import { Field, TextInput } from "@/ui/forms";

import { AuthShell } from "./AuthShell";

/**
 * Login por magic link. Cadastro público não existe: o banco recusa e-mails fora da
 * allowlist. A tela responde sempre a mesma coisa, para não revelar quem está na lista.
 */
export function LoginPage() {
  const { session, loading, sendMagicLink } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && session) return <Navigate to="/app" replace />;

  return (
    <AuthShell>
      {sent ? (
        <div className="space-y-3" role="status">
          <Mail className="size-6 text-gold" />
          <h1 className="text-[22px] font-semibold">Confira seu e-mail</h1>
          <p className="text-[14px] text-muted">
            Se o seu e-mail estiver na lista de convidados, você vai receber um link de acesso em instantes. Ele funciona em
            qualquer aparelho, uma vez só, por 1 hora.
          </p>
          <button type="button" onClick={() => setSent(false)} className="text-[14px] text-accent underline-offset-2 hover:underline">
            Usar outro e-mail
          </button>
        </div>
      ) : (
        <form
          className="space-y-5"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              await sendMagicLink(email);
              setSent(true);
            } catch (err) {
              setError(err instanceof Error ? err.message : "Não foi possível enviar agora.");
            } finally {
              setBusy(false);
            }
          }}
        >
          <div>
            <h1 className="text-[22px] font-semibold">Entrar</h1>
            <p className="mt-1 text-[14px] text-muted">Acesso só para convidados. Enviamos um link, sem senha.</p>
          </div>
          <Field label="E-mail" htmlFor="login-email" error={error}>
            <TextInput
              id="login-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="voce@exemplo.com"
            />
          </Field>
          <PrimaryButton type="submit" disabled={busy || !email} className="w-full justify-center">
            Enviar link de acesso <ArrowRight className="size-4" />
          </PrimaryButton>
        </form>
      )}
    </AuthShell>
  );
}
