import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "", // Set base to an empty string for relative paths
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
      include: /\.[jt]sx?$/,
    }),
  ],
});
