import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// As variáveis VITE_* ficam no .env da raiz do repositório (mesmo arquivo do backend).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  envDir: "..",
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  build: {
    target: "es2022",
    sourcemap: true,
    rolldownOptions: {
      output: {
        // Bibliotecas grandes em arquivos próprios: baixam em paralelo e ficam em cache
        // entre deploys que só mudam o código do app.
        codeSplitting: {
          groups: [
            { name: "react", test: /node_modules[\/](react|react-dom|react-router|scheduler)[\/]/ },
            { name: "charts", test: /node_modules[\/](recharts|d3-[^\/]+|victory-vendor)[\/]/ },
            { name: "supabase", test: /node_modules[\/]@supabase[\/]/ },
            { name: "motion", test: /node_modules[\/](motion|framer-motion|motion-dom|motion-utils)[\/]/ },
          ],
        },
      },
    },
  },
});
