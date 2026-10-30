import { ArrowRight, LogIn } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "@/auth/AuthProvider";
import { PrimaryButton } from "@/ui/controls";

import { AuthShell } from "./AuthShell";

/**
 * Destino do link do e-mail (/entrar?token_hash=...). O link só é gasto no clique do botão:
 * filtros de e-mail que abrem links sozinhos não clicam, e o código vale em qualquer
 * navegador ou aparelho (não depende de nada guardado no navegador que pediu o link).
 */
export function ConfirmLoginPage() {
  const { session, loading, confirmMagicLink } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const tokenHash = params.get("token_hash");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!tokenHash) return <Navigate to={!loading && session ? "/app" : "/login"} replace />;

  return (
    <AuthShell>
      {failed ? (
        <div className="space-y-3" role="alert">
          <h1 className="text-[22px] font-semibold">Link expirado</h1>
          <p className="text-[14px] text-muted">Esse link já foi usado ou passou de 1 hora. Peça um novo, leva um instante.</p>
          <Link to="/login" className="inline-flex items-center gap-1.5 text-[14px] font-medium text-accent underline-offset-2 hover:underline">
            Pedir outro link <ArrowRight className="size-4" />
          </Link>
        </div>
      ) : (
        <div className="space-y-5">
          <div>
            <h1 className="text-[22px] font-semibold">Entrar no Cauri</h1>
            <p className="mt-1 text-[14px] text-muted">Confirme para entrar neste aparelho.</p>
          </div>
          <PrimaryButton
            type="button"
            disabled={busy}
            className="w-full justify-center"
            onClick={async () => {
              setBusy(true);
              const ok = await confirmMagicLink(tokenHash);
              if (ok) navigate("/app", { replace: true });
              else {
                setFailed(true);
                setBusy(false);
              }
            }}
          >
            <LogIn className="size-4" /> Entrar
          </PrimaryButton>
        </div>
      )}
    </AuthShell>
  );
}
