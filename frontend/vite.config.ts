import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Plotly's basic scientific bundle is intentionally large; keep it in a
  // stable vendor chunk and set the warning threshold to its measured size.
  build: {
    chunkSizeWarningLimit: 1_200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          return id.includes("plotly.js-basic-dist-min") || id.includes("react-plotly.js")
            ? "plotly"
            : undefined;
        },
      },
    },
  },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    proxy: {
      "/api/v1": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
