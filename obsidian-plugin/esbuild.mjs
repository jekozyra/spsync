import builtins from "builtin-modules";
import esbuild from "esbuild";

await esbuild.build({
  entryPoints: ["main.ts"],
  bundle: true,
  external: ["obsidian", "electron", ...builtins],
  format: "cjs",
  target: "es2020",
  platform: "node",
  outfile: "main.js",
  logLevel: "info",
});
