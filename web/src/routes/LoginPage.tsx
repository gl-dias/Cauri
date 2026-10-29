import { ArrowRight, Mail } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { Link, Navigate } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { Background } from "@/ui/Background";
import { PrimaryButton } from "@/ui/controls";
import { Field, TextInput } from "@/ui/forms";
import { itemVariants, staticVariants } from "@/ui/motion";

/**
 * Login por magic link. Cadastro público não existe: o banco recusa e-mails fora da
 * allowlist. A tela responde sempre a mesma coisa, para não revelar quem está na lista.
 */
export function LoginPage() {
  const reduced = useReducedMotion();
  const { session, loading, sendMagicLink } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && session) return <Navigate to="/app" replace />;

  return (
    <>
      <Background />
      <main className="grid min-h-dvh place-items-center px-4 py-10">
        <motion.section
          variants={reduced ? staticVariants : itemVariants}
          initial="hidden"
          animate="show"
          className="glass-card w-full max-w-[420px] p-7 sm:p-8"
        >
          <div className="mb-6 flex items-center gap-2.5">
            <span
              className="grid size-10 place-items-center rounded-[14px] shadow-card"
              style={{ background: "linear-gradient(135deg, var(--cauri-avatar-from), var(--cauri-avatar-to))" }}
              aria-hidden
            >
              <svg viewBox="0 0 64 64" className="size-6">
                <path d="M42 22a14 14 0 1 0 0 20" fill="none" stroke="#fff" strokeWidth="7" strokeLinecap="round" />
              </svg>
            </span>
            <span className="text-[18px] font-semibold tracking-tight">Cauri</span>
          </div>
          {sent ? (
            <div className="space-y-3" role="status">
              <Mail className="size-6 text-gold" />
              <h1 className="text-[22px] font-semibold">Confira seu e-mail</h1>
              <p className="text-[14px] text-muted">
                Se o seu e-mail estiver na lista de convidados, você vai receber um link de acesso em instantes. Abra o link
                neste mesmo navegador.
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
          <p className="mt-6 border-t border-white/10 pt-5 text-center text-[13px] text-muted">
            Só quer conhecer?{" "}
            <Link to="/demo" className="font-medium text-ink underline decoration-white/30 underline-offset-2 hover:decoration-white">
              Veja a demonstração
            </Link>
          </p>
        </motion.section>
      </main>
    </>
  );
}
