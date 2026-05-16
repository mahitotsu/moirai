import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      // Chat requests are forwarded to the Python proxy (proxy.py / uvicorn :8001)
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});
