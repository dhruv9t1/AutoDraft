import officeAddins from "eslint-plugin-office-addins";
import tsParser from "@typescript-eslint/parser";
import tsPlugin from "@typescript-eslint/eslint-plugin";

export default [
  ...officeAddins.configs.recommended,
  {
    plugins: {
      "office-addins": officeAddins,
      "@typescript-eslint": tsPlugin,
    },
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2020,
      sourceType: "module",
      globals: {
        // Browser globals
        window: "readonly",
        document: "readonly",
        console: "readonly",
        navigator: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        fetch: "readonly",
        Response: "readonly",
        Request: "readonly",
        URL: "readonly",
        URLSearchParams: "readonly",
        AbortController: "readonly",
        performance: "readonly",
        TextDecoder: "readonly",
        TextEncoder: "readonly",
        ReadableStream: "readonly",
        btoa: "readonly",
        atob: "readonly",
        process: "readonly",
        __dirname: "readonly",
        require: "readonly",
        globalThis: "readonly",
        // Office.js globals
        Word: "readonly",
        Office: "readonly",
      },
    },
    rules: {
      // Disable no-undef for TypeScript files — TypeScript handles this check
      "no-undef": "off",
      // Allow _ prefixed unused variables (convention for intentionally unused params)
      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
  {
    // Ignore patterns
    ignores: [
      "node_modules/**",
      "dist/**",
      "scripts/**",
      "src/test/**",
      "src/**/*.test.ts",
      "src/**/*.test.tsx",
    ],
  },
];
