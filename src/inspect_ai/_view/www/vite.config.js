import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { resolve } from "path";
import dts from "vite-plugin-dts";
import getVersionInfo from "./scripts/get-version.js";

export default defineConfig(({ mode }) => {
  const isLibrary = mode === "library";
  const versionInfo = getVersionInfo();

  const baseConfig = {
    plugins: [
      react({
        jsxRuntime: "automatic",
        fastRefresh: !isLibrary,
      }),
    ],
    resolve: {
      dedupe: [
        "react",
        "react-dom",
        "@codemirror/state",
        "@codemirror/view",
        "@codemirror/language",
      ],
    },
    define: {
      __DEV_WATCH__: JSON.stringify(process.env.DEV_LOGGING === "true"),
      __LOGGING_FILTER__: JSON.stringify(
        process.env.DEV_LOGGING_NAMESPACES || "*",
      ),
      __VIEW_SERVER_API_URL__: JSON.stringify(
        process.env.VIEW_SERVER_API_URL || "/api",
      ),
      __VIEWER_VERSION__: JSON.stringify(versionInfo.version),
      __VIEWER_COMMIT__: JSON.stringify(versionInfo.commitHash),
    },
  };

  if (isLibrary) {
    // Library build configuration
    return {
      ...baseConfig,
      plugins: [
        ...baseConfig.plugins,
        dts({
          insertTypesEntry: true,
          exclude: ["**/*.test.ts", "**/*.test.tsx", "src/tests/**/*"],
        }),
      ],
      build: {
        outDir: "lib",
        lib: {
          entry: resolve(__dirname, "src/index.ts"),
          name: "InspectAILogViewer",
          fileName: "index",
          formats: ["es"],
        },
        rollupOptions: {
          external: ["react", "react-dom"],
          output: {
            globals: {
              react: "React",
              "react-dom": "ReactDOM",
              "react-router-dom": "ReactRouterDOM",
            },
            assetFileNames: (assetInfo) => {
              if (assetInfo.name && assetInfo.name.endsWith(".css")) {
                return "styles/[name].[ext]";
              }
              return "assets/[name].[ext]";
            },
          },
        },
        cssCodeSplit: false,
        sourcemap: true,
        minify: true,
      },
    };
  } else {
    // App build configuration
    return {
      ...baseConfig,
      base: "",
      server: {
        proxy: {
          '/api': {
            target: 'http://127.0.0.1:7575', // when running `inspect view` locally
            changeOrigin: true,
          }
        }
      },
      build: {
        minify: true,
        rollupOptions: {
          output: {
            entryFileNames: `assets/index.js`,
            chunkFileNames: `assets/[name].js`,
            assetFileNames: `assets/[name].[ext]`,
            manualChunks(id) {
              if (id.includes('mathjax') || id.includes('markdown-it-mathjax3')) {
                return 'vendor-mathjax';
              }
              if (id.includes('@codemirror') || id.includes('@lezer')) {
                return 'vendor-codemirror';
              }
              if (id.includes('ag-grid')) {
                return 'vendor-ag-grid';
              }
            },
          },
        },
        sourcemap: true,
      },
    };
  }
});
