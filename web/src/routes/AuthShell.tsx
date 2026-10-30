import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Background } from "@/ui/Background";
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
