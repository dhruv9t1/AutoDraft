/**
 * Local-only frontend diagnostic receiver.
 *
 * It is intentionally disabled unless FRONTEND_LOGGER_ENABLE=true and always
 * binds to loopback. It does not persist logs and ignores arbitrary context.
 */
const http = require("http");
const url = require("url");

if (process.env.FRONTEND_LOGGER_ENABLE !== "true") {
  console.error(
    "Frontend logger server is disabled. Set FRONTEND_LOGGER_ENABLE=true for local development."
  );
  process.exit(2);
}

const HOST = "127.0.0.1";
const PORT = Number(process.env.FRONTEND_LOGGER_PORT || 3002);
const MAX_BODY = 16 * 1024;

function isAllowedOrigin(origin) {
  if (!origin) return true;
  try {
    const u = new URL(origin);
    return (
      (u.protocol === "http:" || u.protocol === "https:") &&
      (u.hostname === "localhost" || u.hostname === "127.0.0.1")
    );
  } catch {
    return false;
  }
}

function clean(value) {
  return String(value || "")
    .replace(/[\r\n\t]+/g, " ")
    .slice(0, 600);
}

const server = http.createServer((req, res) => {
  const pathname = url.parse(req.url, true).pathname;
  const origin = req.headers.origin;
  if (!isAllowedOrigin(origin)) {
    res.writeHead(403, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "origin denied" }));
    return;
  }
  if (origin) res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Vary", "Origin");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "no-store");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }
  if (req.method !== "POST" || pathname !== "/logs") {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not found" }));
    return;
  }

  let body = "";
  let tooLarge = false;
  req.on("data", (chunk) => {
    if (tooLarge) return;
    body += chunk.toString();
    if (Buffer.byteLength(body, "utf8") > MAX_BODY) tooLarge = true;
  });
  req.on("end", () => {
    if (tooLarge) {
      res.writeHead(413, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "log entry too large" }));
      return;
    }
    try {
      const parsed = JSON.parse(body);
      const level = ["log", "info", "warn", "error", "debug"].includes(parsed.level)
        ? parsed.level
        : "log";
      const message = clean(parsed.message);
      const prefix = level.toUpperCase();
      // Message has already been privacy-filtered client-side. Context is deliberately ignored.
      console.log(`[FRONTEND ${prefix}] ${message}`);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "logged" }));
    } catch {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "invalid json" }));
    }
  });
});

server.listen(PORT, HOST, () => {
  console.log(`Local frontend diagnostic receiver listening on http://${HOST}:${PORT}`);
  console.log("No logs are persisted. Stop this process when diagnostics are complete.");
});
