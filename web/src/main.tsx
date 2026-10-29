import "@fontsource-variable/inter";
import "./theme/glass.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import { ComingSoon } from "./routes/ComingSoon";
import { DemoLayout } from "./routes/DemoLayout";
import { applyTheme } from "./theme/tokens";

applyTheme();

// Telas carregadas sob demanda: o gráfico (Recharts) só baixa quando a tela que usa abre.
const HomePage = lazy(() => import("./features/home/HomePage").then((m) => ({ default: m.HomePage })));
const page = (node: React.ReactNode) => <Suspense fallback={null}>{node}</Suspense>;

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60_000, refetchOnWindowFocus: false, retry: 1 } },
});

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/demo" replace /> },
  {
    path: "/demo",
    element: <DemoLayout />,
    children: [
      { index: true, element: page(<HomePage />) },
      { path: "carteira", element: <ComingSoon title="Carteira" /> },
      { path: "lancamentos", element: <ComingSoon title="Lançamentos" /> },
      { path: "importar", element: <ComingSoon title="Importar" /> },
      { path: "assistente", element: <ComingSoon title="Assistente" /> },
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
