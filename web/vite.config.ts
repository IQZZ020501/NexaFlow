import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/auth": "http://localhost:8000",
      "/users": "http://localhost:8000",
      "/workspaces": "http://localhost:8000",
      "/audit-logs": "http://localhost:8000",
      "/model-providers": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
})
