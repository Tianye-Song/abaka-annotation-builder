import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, Vite serves the UI on :5173 and proxies data calls to FastAPI on :8000.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/media": "http://localhost:8000" } },
});
