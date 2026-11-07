import { spawn } from "node:child_process";
import { createConnection } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..", "..");
const python = resolve(repoRoot, ".venv", "Scripts", "python.exe");
const vite = resolve(webRoot, "node_modules", "vite", "bin", "vite.js");
const children = [];

function spawnVisible(file, args, cwd = webRoot) {
  const child = spawn(file, args, { cwd, stdio: "inherit", windowsHide: true });
  children.push(child);
  child.once("exit", (code) => {
    if (!stopping) void shutdown(code ?? 1);
  });
  return child;
}

async function run(file, args) {
  const child = spawn(file, args, { cwd: webRoot, stdio: "inherit", windowsHide: true });
  const code = await new Promise((resolveExit) => child.once("exit", (value) => resolveExit(value ?? 1)));
  if (code !== 0) throw new Error(`build exited with code ${code}`);
}

async function waitFor(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) {
        await response.body?.cancel();
        return;
      }
    } catch { /* startup is still in progress */ }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 200));
  }
  throw new Error(`startup timed out: ${url}`);
}

function portIsOpen(port) {
  return new Promise((resolvePort) => {
    const socket = createConnection({ host: "127.0.0.1", port });
    socket.once("connect", () => { socket.destroy(); resolvePort(true); });
    socket.once("error", () => resolvePort(false));
  });
}

async function requireFreePorts() {
  for (const port of [8000, 4173]) {
    if (await portIsOpen(port)) throw new Error(`port ${String(port)} is already in use; refusing to start beside an unknown service`);
  }
}

let stopping = false;
let cleanupPromise;
function shutdown(code = 0) {
  if (cleanupPromise) return cleanupPromise;
  stopping = true;
  cleanupPromise = (async () => {
    await Promise.all(children.map(async (child) => {
      if (child.exitCode !== null) return;
      child.kill("SIGTERM");
      await Promise.race([
        new Promise((resolveExit) => child.once("exit", resolveExit)),
        new Promise((resolveDelay) => setTimeout(resolveDelay, 3_000)),
      ]);
      if (child.exitCode === null) {
        child.kill("SIGKILL");
        await Promise.race([
          new Promise((resolveExit) => child.once("exit", resolveExit)),
          new Promise((resolveDelay) => setTimeout(resolveDelay, 2_000)),
        ]);
      }
    }));
    const childStillRunning = children.some((child) => child.exitCode === null);
    for (const port of [8000, 4173]) {
      if (await portIsOpen(port)) console.error(`[web-v2] port ${String(port)} is still in use after cleanup`);
    }
    process.exitCode = childStillRunning ? 1 : code;
  })();
  return cleanupPromise;
}

process.once("SIGINT", () => { void shutdown(0); });
process.once("SIGTERM", () => { void shutdown(0); });

try {
  console.log("[web-v2] building production assets...");
  await run(process.execPath, [vite, "build"]);
  await requireFreePorts();
  spawnVisible(python, ["-m", "uvicorn", "parking_opt.api.app:app", "--app-dir", resolve(repoRoot, "src"), "--host", "127.0.0.1", "--port", "8000", "--http", "h11"]);
  spawnVisible(process.execPath, [vite, "preview", "--host", "127.0.0.1", "--port", "4173", "--strictPort"]);
  await Promise.all([
    waitFor("http://127.0.0.1:8000/api/v2/health"),
    waitFor("http://127.0.0.1:4173"),
  ]);
  console.log("[web-v2] ready: http://127.0.0.1:4173");
  console.log("[web-v2] press Ctrl+C to stop both services");
} catch (error) {
  console.error(error);
  await shutdown(1);
}
