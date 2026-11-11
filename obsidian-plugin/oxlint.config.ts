import { defineConfig } from "oxlint";

// The rules and plugins match lighthouse-project-template's oxlint.config.ts.
export default defineConfig({
  ignorePatterns: [
    ".agent/**",
    ".agents/**",
    ".claude/**",
    ".codex/**",
    ".continue/**",
    ".cursor/**",
    ".gemini/**",
    ".opencode/**",
    ".pi/**",
    ".playwright-cli/**",
    ".roo/**",
    ".windsurf/**",
    "tools/oxlint/anti-slop/**",
    // esbuild generates the plugin bundle from main.ts.
    "main.js",
  ],
  plugins: ["typescript", "unicorn", "oxc", "import", "react", "react-perf"],
  categories: {
    correctness: "error",
    suspicious: "error",
    perf: "error",
  },
  env: { builtin: true },
  jsPlugins: [
    { name: "anti-slop", specifier: "./tools/oxlint/anti-slop/index.ts" },
    { name: "anti-slop-effect", specifier: "./tools/oxlint/anti-slop/effect/index.ts" },
  ],
  rules: {
    curly: "error",
    "no-plusplus": "error",
    // The template's React app uses the automatic JSX runtime. The plugin has no JSX.
    "react/react-in-jsx-scope": "off",
    // CSS imports initialize Vite's style pipeline in the template. The plugin imports no CSS.
    "import/no-unassigned-import": ["error", { allow: ["**/*.css"] }],
    // This rule targets Express, which the plugin does not use.
    "oxc/no-async-endpoint-handlers": "off",
    "unicorn/prefer-import-meta-properties": "error",
    "oxc/no-accumulating-spread": "error",
    "anti-slop/no-array-filter-map": "error",
    "anti-slop/no-reduce-accumulator-copy": "error",
    "anti-slop/no-chained-type-assertions": "error",
    "anti-slop/no-conditional-empty-object-spread": "error",
    "anti-slop/no-empty-for-loop-header": "error",
    "anti-slop/no-known-value-widening": "error",
    "anti-slop/no-module-mocking": "error",
    "anti-slop/no-object-parameters": "error",
    "anti-slop/no-reflect-apply": "error",
    "anti-slop/no-reflect-get": "error",
    "anti-slop/no-runtime-typeof": ["error", { allowInTypeGuards: true }],
    "anti-slop/no-shape-in-symbol-names": "error",
    "anti-slop/no-unknown-parameters": "error",
    "anti-slop/no-unknown-returns": "error",
    "anti-slop/no-unknown-type-aliases": "error",
    "anti-slop/no-unsafe-dictionary-type": "error",
    "anti-slop/no-widen-then-assert": "error",
    "anti-slop/require-readable-spacing": "error",
    "anti-slop/require-safety-comment-for-type-assertion": "error",
    "anti-slop-effect/no-manual-effect-error-tag": "error",
    "anti-slop-effect/no-manual-tag-comparison": "error",
    "anti-slop-effect/no-manual-tagged-construction": "error",
    "anti-slop-effect/no-service-constructor-imports": "error",
    "anti-slop-effect/prefer-effect-match": "error",
  },
});
