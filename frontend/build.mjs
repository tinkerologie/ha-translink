import { build } from "esbuild";
await build({
  entryPoints: ["src/index.ts"],
  outfile: "../custom_components/translink/frontend/translink-cards.js",
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  // Preserve template semantics while emitting escaped strings, so Lit's
  // significant whitespace does not become trailing whitespace in the bundle.
  supported: { "template-literal": false },
  legalComments: "inline",
});
