import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/e/": { target: "http://localhost:8000", bypass: (req) => (req.url.endsWith(".webmanifest") ? undefined : req.url) } } },
});
