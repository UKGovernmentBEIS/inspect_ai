import globals from "globals";
import pluginJs from "@eslint/js";

export default [
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        bootstrap: "readonly",
        JSON5: "readonly",
        Prism: "readonly",
        showdown: "readonly",
      },
    },
  },
  pluginJs.configs.recommended,
  {
    ignores: ["libs/**", "preact/**"],
  },
];
