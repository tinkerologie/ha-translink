import { spawn } from "node:child_process";
// Playwright enables FORCE_COLOR for workers. Avoid Node's conflicting-color warning.
const env = { ...process.env };
delete env.NO_COLOR;
const child = spawn(
  process.execPath,
  ["node_modules/@playwright/test/cli.js", "test", ...process.argv.slice(2)],
  { stdio: "inherit", env },
);
child.on("error", () => {
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code ?? 1;
});
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
