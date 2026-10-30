import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Background } from "@/ui/Background";
import { Brand } from "@/ui/Brand";
import { itemVariants, staticVariants } from "@/ui/motion";

/** Cartão das telas de acesso (pedir o link e confirmar a entrada). */
export function AuthShell({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
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
          <div className="mb-6">
            <Brand />
          </div>
          {children}
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
