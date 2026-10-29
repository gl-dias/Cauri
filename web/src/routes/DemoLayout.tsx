import { motion, useReducedMotion } from "motion/react";
import { useMemo } from "react";
import { Outlet, useLocation } from "react-router";

import { SourceProvider, useMe } from "@/data/context";
import { createDemoSource } from "@/data/source";
import { tokens } from "@/theme/tokens";
import { AppShell } from "@/ui/Shell";

function DemoFrame() {
  const me = useMe();
  const location = useLocation();
  const reduced = useReducedMotion();
  return (
    <AppShell base="/demo" name={me.data?.display_name ?? "Investidor Demo"} demo>
      {/* Troca de tela: crossfade curto. */}
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

/** /demo: público, sem login, só leitura, carteira fictícia. */
export function DemoLayout() {
  const source = useMemo(() => createDemoSource(), []);
  return (
    <SourceProvider source={source}>
      <DemoFrame />
    </SourceProvider>
  );
}
