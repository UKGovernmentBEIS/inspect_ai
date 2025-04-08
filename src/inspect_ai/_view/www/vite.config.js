import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  mode: "development",
  base: "",
  build: {
    minify: false,
    rollupOptions: {
      output: {
        entryFileNames: `assets/index.js`,
        chunkFileNames: `assets/[name].js`,
        assetFileNames: `assets/[name].[ext]`,
      },
    },
    sourcemap: true,
  },
  plugins: [
    react({
      jsxRuntime: "automatic",
      fastRefresh: true,
    }),
  ],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  define: {
    __DEV_WATCH__: JSON.stringify(process.env.DEV_LOGGING === "true"),
    __LOGGING_FILTER__: JSON.stringify(
      process.env.DEV_LOGGING_NAMESPACES || "*",
    ),
  },
});
