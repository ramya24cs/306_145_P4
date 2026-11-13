import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The React dev server (5173) forwards /api/* to Flask (5000): browser -> Vite -> Flask -> SQLite.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "http://127.0.0.1:5000", changeOrigin: true } } },
});
