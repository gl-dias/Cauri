import type { Variants } from "motion/react";

import { tokens } from "@/theme/tokens";

/** Entrada da página: os cards aparecem em sequência (40 ms), com fade e um blur saindo. */
export const pageVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: tokens.motion.stagger, delayChildren: 0.02 } },
};

export const itemVariants: Variants = {
  hidden: { opacity: 0, y: 10, filter: "blur(6px)" },
  show: {
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { duration: 0.42, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Sem animação de entrada (prefers-reduced-motion): só aparece. */
export const staticVariants: Variants = { hidden: { opacity: 1 }, show: { opacity: 1 } };

export const hoverLift = { y: tokens.motion.hoverLift, transition: tokens.motion.spring };
