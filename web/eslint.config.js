// Линтер клиента (openspec/changes/tech-debt-web): правила TypeScript без проверки типов
// (типы проверяет tsc) и правила хуков React. Запускается в `npm run build`, а значит в CI.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // Неиспользуемое ловит tsc (noUnusedLocals, noUnusedParameters); `_` — сознательно пропущенный аргумент.
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["eslint.config.js", "vite.config.ts", "vitest.config.ts"],
    languageOptions: { globals: globals.node },
  },
);
