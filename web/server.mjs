import { readFileSync } from "node:fs";
import { createServer } from "node:https";
import next from "next";
import nextEnv from "@next/env";

const { loadEnvConfig } = nextEnv;

const root = process.cwd();
loadEnvConfig(root);

const host = process.env.KOMI_WEB_HOST ?? "0.0.0.0";
const port = Number(process.env.KOMI_WEB_PORT ?? "3000");
const certificatePath = process.env.KOMI_TLS_CERT_FILE ?? "";
const privateKeyPath = process.env.KOMI_TLS_KEY_FILE ?? "";
if (!certificatePath || !privateKeyPath) {
  throw new Error("LAN HTTPS certificate is not configured");
}
for (const variable of [
  "KOMI_WEB_ACCESS_HASH",
  "KOMI_WEB_AUTH_EPOCH",
  "KOMI_WEB_AUTH_STATE_FILE",
  "KOMI_WEB_SESSION_SECRET",
]) {
  if (!process.env[variable]) throw new Error(`Required security configuration is missing: ${variable}`);
}

const app = next({ dev: false, hostname: host, port, dir: root });
const handle = app.getRequestHandler();
await app.prepare();

const server = createServer(
  { cert: readFileSync(certificatePath), key: readFileSync(privateKeyPath), minVersion: "TLSv1.2" },
  (request, response) => {
    request.headers["x-komi-remote-address"] = request.socket.remoteAddress ?? "unknown";
    void handle(request, response);
  },
);

server.listen(port, host, () => {
  process.stdout.write(`KOMI Report Web HTTPS listening on ${host}:${port}\n`);
});
