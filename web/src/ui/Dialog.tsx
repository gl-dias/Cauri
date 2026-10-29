import { X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Diálogo de vidro: fecha com Esc ou clique fora e devolve o foco a quem abriu. */
export function Dialog({ open, onClose, title, children, footer, wide = false }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const reduced = useReducedMotion();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    panel.current?.querySelector<HTMLElement>("input, select, textarea")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 grid place-items-end bg-black/55 p-3 sm:place-items-center sm:p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
        >
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className={`glass-card flex max-h-[92dvh] w-full flex-col overflow-hidden [background:rgba(28,22,18,0.84)] ${
              wide ? "sm:max-w-3xl" : "sm:max-w-lg"
            }`}
            initial={reduced ? false : { y: 24, opacity: 0, filter: "blur(6px)" }}
            animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
            exit={reduced ? { opacity: 0 } : { y: 16, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="flex items-center justify-between gap-3 border-b border-white/10 px-5 py-4 sm:px-6">
              <h2 className="text-[17px] font-semibold">{title}</h2>
              <button
                type="button"
                onClick={onClose}
                aria-label="Fechar"
                className="grid size-9 place-items-center rounded-full text-muted hover:bg-white/10 hover:text-ink"
              >
                <X className="size-[18px]" />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-5 py-5 sm:px-6">{children}</div>
            {footer ? (
              <footer className="flex flex-wrap justify-end gap-2.5 border-t border-white/10 px-5 py-4 sm:px-6">{footer}</footer>
            ) : null}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}
