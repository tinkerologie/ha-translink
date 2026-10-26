import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
const root = resolve(import.meta.dirname, "../../..");
const types = {
  ".js": "text/javascript",
  ".json": "application/json",
  ".html": "text/html",
};
createServer(async (req, res) => {
  const pathname = new URL(req.url, "http://localhost").pathname;
  const path = resolve(
    root,
    `.${pathname === "/" ? "/frontend/test/browser/index.html" : pathname}`,
  );
  if (!path.startsWith(root + "/")) {
    res.writeHead(403).end();
    return;
  }
  try {
    res
      .writeHead(200, { "Content-Type": types[extname(path)] ?? "text/plain" })
      .end(await readFile(path));
  } catch {
    res.writeHead(404).end();
  }
}).listen(4178, "127.0.0.1");
