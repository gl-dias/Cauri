import { LockKeyhole } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { SourceProvider, useMe } from "@/data/context";
import { tokens } from "@/theme/tokens";
import { Background } from "@/ui/Background";
import { GlassButton } from "@/ui/controls";
import { GlassCard } from "@/ui/GlassCard";
import { AppShell } from "@/ui/Shell";

function Centered({ children }: { children: ReactNode }) {
  return (
    <>
      <Background />
      <main className="grid min-h-dvh place-items-center px-4">{children}</main>
    </>
  );
}

function AppFrame() {
  const me = useMe();
  const { signOut } = useAuth();
  const location = useLocation();
  const reduced = useReducedMotion();

  if (me.isLoading) return <Centered>{null}</Centered>;
  if (me.isError || !me.data) {
    // Sessão válida, mas fora da allowlist (ou removido dela): o RLS não devolve nada.
    return (
      <Centered>
        <GlassCard lift={false} className="max-w-md text-center">
          <LockKeyhole className="mx-auto mb-3 size-6 text-gold" />
          <h1 className="text-[20px] font-semibold">Acesso restrito a convidados</h1>
          <p className="mt-1 mb-5 text-[14px] text-muted">Este e-mail não está na lista de convidados do Cauri.</p>
          <GlassButton onClick={() => void signOut()} className="mx-auto">
            Sair
          </GlassButton>
        </GlassCard>
      </Centered>
    );
  }
  const isAdmin = me.data.role === "admin";
  if (location.pathname.startsWith("/app/admin") && !isAdmin) return <Navigate to="/app" replace />;

  return (
    <AppShell base="/app" name={me.data.display_name} demo={false} admin={isAdmin} onSignOut={() => void signOut()}>
      <motion.div
        key={location.pathname}
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: tokens.motion.pageFade }}
      >
        <Outlet />
      </motion.div>
    </AppShell>
  );
}

/** /app: privado. Sem sessão, vai para o login. */
export function AppLayout() {
  const { session, loading, source } = useAuth();
  const { search } = useLocation();
  if (loading) return <Centered>{null}</Centered>;
  // Link do e-mail que caiu no endereço padrão do Supabase (Site URL = /app): confirma em /entrar.
  if (new URLSearchParams(search).has("token_hash")) return <Navigate to={`/entrar${search}`} replace />;
  if (!session) return <Navigate to="/login" replace />;
  return (
    <SourceProvider source={source}>
      <AppFrame />
    </SourceProvider>
  );
}
