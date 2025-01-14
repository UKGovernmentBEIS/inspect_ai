import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import preact from "@preact/preset-vite";
import prism from "vite-plugin-prismjs";

export default defineConfig({
  base: "", // Set base to an empty string for relative paths
  build: {
    // It's important we don't minify, as we check the bundled code into git so
    // that users don't need to bundle themselves. If we minify, that balloons
    // the size of the github repo because even minor changes will result in
    // enormous diffs.
    minify: false,
    rollupOptions: {
      output: {
        // This configuration ensures a consistent name of output files each
        // build, which is important given we check them in.
        entryFileNames: `assets/index.js`,
        chunkFileNames: `assets/[name].js`,
        assetFileNames: `assets/[name].[ext]`,
      },
    },
    sourcemap: true,
  },
  plugins: [
    // Configure both Preact and React plugins
    preact(),
    react({
      // Only apply React plugin to .tsx files
      include: /\.(tsx|ts)$/,
    }),
    prism({
      languages: ["javascript", "css", "clike", "bash", "python", "python"],
      css: true,
    }),
  ],
  resolve: {
    // Add aliases to handle both React and Preact
    alias: {
      // This allows existing Preact code to keep working
      'react': 'preact/compat',
      'react-dom': 'preact/compat',
      'react-dom/test-utils': 'preact/test-utils'
    }
  }
});
