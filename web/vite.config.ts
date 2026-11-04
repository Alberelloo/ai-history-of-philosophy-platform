import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке запросы /api уходят в сервис библиотеки; в сборке клиент раздаёт сам сервис.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8001" } },
  build: { outDir: "dist", emptyOutDir: true },
});
