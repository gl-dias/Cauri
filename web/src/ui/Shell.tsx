import { Bell, House, LayoutGrid, ListOrdered, MessageCircle, Search, Upload, Wallet, type LucideIcon } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";

import { BACKGROUNDS, type BackgroundSlug } from "@/theme/backgrounds";
import { tokens } from "@/theme/tokens";

import { Background } from "./Background";
import { IconButton } from "./controls";
import { Avatar } from "./viz";

export type NavItem = { to: string; label: string; icon: LucideIcon; end?: boolean };

export function navItems(base: string): NavItem[] {
  return [
    { to: base, label: "Início", icon: House, end: true },
    { to: `${base}/carteira`, label: "Carteira", icon: Wallet },
    { to: `${base}/lancamentos`, label: "Lançamentos", icon: ListOrdered },
    { to: `${base}/importar`, label: "Importar", icon: Upload },
    { to: `${base}/assistente`, label: "Assistente", icon: MessageCircle },
  ];
}

function Logo({ demo }: { demo: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
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
      {demo ? (
        <span className="rounded-full border border-white/25 bg-white/10 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-ink uppercase">
          Demo
        </span>
      ) : null}
    </div>
  );
}

function NavPills({ items }: { items: NavItem[] }) {
  const reduced = useReducedMotion();
  return (
    <nav aria-label="Seções" className="glass-pill hidden items-center gap-1 p-1 lg:flex">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `relative flex h-10 items-center gap-2 rounded-full px-4 text-[14px] font-medium transition-colors ${
              isActive ? "text-ink" : "text-muted hover:text-ink"
            }`
          }
        >
          {({ isActive }) => (
            <>
              {isActive ? (
                <motion.span
                  layoutId="nav-pill"
                  transition={reduced ? { duration: 0 } : tokens.motion.spring}
                  className="absolute inset-0 rounded-full border border-white/25 bg-white/20"
                />
              ) : null}
              <item.icon className="relative size-[18px]" strokeWidth={1.9} />
              <span className="relative">{item.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

export function TopBar({ items, name, demo, notifications = 0 }: { items: NavItem[]; name: string; demo: boolean; notifications?: number }) {
  return (
    <header className="fixed inset-x-0 top-0 z-30 px-4 pt-4 sm:px-6 sm:pt-5">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Logo demo={demo} />
          <IconButton label="Visão geral" className="hidden sm:grid">
            <LayoutGrid className="size-[18px]" strokeWidth={1.9} />
          </IconButton>
        </div>
        <NavPills items={items} />
        <div className="flex items-center gap-2 sm:gap-2.5">
          <IconButton label="Buscar" className="hidden sm:grid">
            <Search className="size-[18px]" strokeWidth={1.9} />
          </IconButton>
          <IconButton label="Notificações" badge={notifications}>
            <Bell className="size-[18px]" strokeWidth={1.9} />
          </IconButton>
          <Avatar name={name} />
        </div>
      </div>
    </header>
  );
}

/** Dock vertical à esquerda (só ícones); no celular vira barra inferior. */
export function Dock({ items }: { items: NavItem[] }) {
  return (
    <nav
      aria-label="Navegação"
      className="glass-pill fixed inset-x-4 bottom-4 z-30 flex items-center justify-around p-1.5 md:inset-x-auto md:top-1/2 md:bottom-auto md:left-5 md:-translate-y-1/2 md:flex-col md:gap-2 md:p-2"
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          aria-label={item.label}
          title={item.label}
          className={({ isActive }) =>
            `grid size-11 place-items-center rounded-full transition-colors ${
              isActive ? "bg-white text-on-light shadow-card" : "text-muted hover:bg-white/15 hover:text-ink"
            }`
          }
        >
          <item.icon className="size-[19px]" strokeWidth={1.9} />
        </NavLink>
      ))}
    </nav>
  );
}

function Footer({ slug }: { slug: BackgroundSlug }) {
  const photo = BACKGROUNDS[slug];
  return (
    <footer className="mt-10 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pb-2 text-center text-[12px] text-subtle">
      <span>Cripto: Data provided by CoinGecko</span>
      <span aria-hidden>·</span>
      <span>
        Foto:{" "}
        <a className="underline decoration-white/30 underline-offset-2 hover:text-ink" href={photo.source} target="_blank" rel="noreferrer">
          {photo.author}
        </a>{" "}
        ({photo.license})
      </span>
      <span aria-hidden>·</span>
      <span>Renda fixa em valor bruto</span>
    </footer>
  );
}

export function AppShell({ base, name, demo, children }: { base: string; name: string; demo: boolean; children: ReactNode }) {
  const items = navItems(base);
  const slug = tokens.background.photo;
  return (
    <>
      <Background slug={slug} />
      <TopBar items={items} name={name} demo={demo} />
      <Dock items={items} />
      <main className="mx-auto max-w-[1600px] px-4 pt-24 pb-28 sm:px-6 sm:pt-28 md:pr-8 md:pb-10 md:pl-[104px]">
        {children}
        <Footer slug={slug} />
      </main>
    </>
  );
}
