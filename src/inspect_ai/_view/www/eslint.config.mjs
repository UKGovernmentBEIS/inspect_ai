import pluginJs from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default [
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
  },
  pluginJs.configs.recommended,
  {
    ignores: ["libs/**", "preact/**", "dist/**", "src/types/log.d.ts"],
  },
  // Add TypeScript support with customized rules for all files
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        project: "./tsconfig.json",
      },
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      // React Hooks rules
      "react-hooks/rules-of-hooks": "warn",
      // "react-hooks/exhaustive-deps": "warn",

      // These are disabled because we didn't have time to fix them, not because they are bad rules
      "no-unused-vars": "off",
    },
  },
  // Add Jest globals for test files
  {
    files: ["**/*.test.{ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.jest,
      },
    },
  },
];