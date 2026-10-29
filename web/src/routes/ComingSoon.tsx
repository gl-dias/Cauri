import { Hammer } from "lucide-react";

import { GlassCard } from "@/ui/GlassCard";

/** Telas que entram na Fase 3b. */
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="grid min-h-[50vh] place-items-center">
      <GlassCard className="max-w-md text-center" lift={false}>
        <Hammer className="mx-auto mb-3 size-6 text-gold" />
        <h1 className="text-[20px] font-semibold">{title}</h1>
        <p className="mt-1 text-[14px] text-muted">Esta tela entra na próxima etapa.</p>
      </GlassCard>
    </div>
  );
}
