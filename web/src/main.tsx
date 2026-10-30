import "@fontsource-variable/inter";
import "./theme/glass.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, Outlet, RouterProvider } from "react-router";

import { AuthProvider } from "./auth/AuthProvider";
import { AppLayout } from "./routes/AppLayout";
import { DemoLayout } from "./routes/DemoLayout";
import { ConfirmLoginPage } from "./routes/ConfirmLoginPage";
import { LoginPage } from "./routes/LoginPage";
import { applyTheme } from "./theme/tokens";

applyTheme();

// Telas carregadas sob demanda: o gráfico (Recharts) só baixa quando a tela que usa abre.
const HomePage = lazy(() => import("./features/home/HomePage").then((m) => ({ default: m.HomePage })));
const PortfolioPage = lazy(() => import("./features/portfolio/PortfolioPage").then((m) => ({ default: m.PortfolioPage })));
const LedgerPage = lazy(() => import("./features/ledger/LedgerPage").then((m) => ({ default: m.LedgerPage })));
const ImportPage = lazy(() => import("./features/import/ImportPage").then((m) => ({ default: m.ImportPage })));
const AssistantPage = lazy(() => import("./features/assistant/AssistantPage").then((m) => ({ default: m.AssistantPage })));
const AdminPage = lazy(() => import("./features/admin/AdminPage").then((m) => ({ default: m.AdminPage })));
const page = (node: React.ReactNode) => <Suspense fallback={null}>{node}</Suspense>;

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60_000, refetchOnWindowFocus: false, retry: 1 } },
});


const appScreens = [
  { index: true, element: page(<HomePage />) },
  { path: "carteira", element: page(<PortfolioPage />) },
  { path: "lancamentos", element: page(<LedgerPage />) },
  { path: "importar", element: page(<ImportPage />) },
  { path: "assistente", element: page(<AssistantPage />) },
];

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/demo" replace /> },
  { path: "/demo", element: <DemoLayout />, children: appScreens },
  // Login e /app dividem um único AuthProvider (um só cliente de sessão). O /demo fica
  // fora dele: não lê nem cria sessão.
  {
    element: (
      <AuthProvider>
        <Outlet />
      </AuthProvider>
    ),
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/entrar", element: <ConfirmLoginPage /> },
      {
        path: "/app",
        element: <AppLayout />,
        children: [...appScreens, { path: "admin", element: page(<AdminPage />) }],
      },
    ],
  },
  { path: "*", element: <Navigate to="/demo" replace /> },
]);

const root = document.getElementById("root");
if (!root) throw new Error("#root ausente");
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
