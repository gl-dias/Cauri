/**
 * Sessão do /app por magic link. O e-mail leva a /entrar?token_hash=... (templates em
 * supabase/templates/), e a sessão nasce do verifyOtp no clique de "Entrar": vale em qualquer
 * navegador, ao contrário do código PKCE, que só funciona onde o link foi pedido. Cadastro
 * aberto é barrado no banco (hook de allowlist), então a tela de login nunca revela se o
 * e-mail está ou não autorizado.
 */
import type { Session } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { createApi } from "@/data/api";
import { createAppClient, createAppSource, type AppSource, type MartsClient } from "@/data/source";

type AuthState = {
  client: MartsClient;
  session: Session | null;
  loading: boolean;
  source: AppSource;
  sendMagicLink(email: string): Promise<void>;
  /** Troca o código do link pela sessão. Falso se o link expirou ou já foi usado. */
  confirmMagicLink(tokenHash: string): Promise<boolean>;
  signOut(): Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

function apiUrl(): string {
  return (import.meta.env.VITE_API_URL as string | undefined) ?? "http://127.0.0.1:8000";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useMemo(() => createAppClient(), []);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void client.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setLoading(false);
    });
    const { data } = client.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setLoading(false);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, [client]);

  const source = useMemo(
    () =>
      createAppSource(
        client,
        createApi(apiUrl(), async () => (await client.auth.getSession()).data.session?.access_token ?? null),
      ),
    [client],
  );

  const value = useMemo<AuthState>(
    () => ({
      client,
      session,
      loading,
      source,
      async sendMagicLink(email) {
        // O resultado não muda a mensagem na tela: recusado pela allowlist ou não, o
        // usuário vê o mesmo texto. Erros só de rede/limite aparecem.
        const { error } = await client.auth.signInWithOtp({
          email: email.trim().toLowerCase(),
          options: { emailRedirectTo: `${window.location.origin}/entrar`, shouldCreateUser: true },
        });
        if (error && (error.status === 429 || error.status === 0 || error.status === undefined)) {
          throw new Error("Não foi possível enviar agora. Tente de novo em alguns minutos.");
        }
      },
      async confirmMagicLink(tokenHash) {
        const { error } = await client.auth.verifyOtp({ token_hash: tokenHash, type: "email" });
        return !error;
      },
      async signOut() {
        await client.auth.signOut();
      },
    }),
    [client, session, loading, source],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("AuthProvider ausente");
  return auth;
}
