import { spawn } from "node:child_process";
import { createConnection } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..", "..");
const python = process.env.PYTHON || resolve(repoRoot, ".venv", "Scripts", "python.exe");
const node = process.execPath;
const vite = resolve(webRoot, "node_modules", "vite", "bin", "vite.js");
const playwright = resolve(webRoot, "node_modules", "@playwright", "test", "cli.js");
const config = resolve(webRoot, "playwright.real.config.ts");

const children = [];
let stopping = false;
let cleanupPromise;
let rejectServiceFailure;
const serviceFailure = new Promise((_, reject) => { rejectServiceFailure = reject; });
function launch(file, args, cwd = webRoot) {
  const child = spawn(file, args, { cwd, stdio: "inherit", windowsHide: true });
  children.push(child);
  return child;
}

function launchService(name, file, args, cwd = webRoot) {
  const child = launch(file, args, cwd);
  child.once("exit", (code) => {
    if (!stopping) rejectServiceFailure(new Error(`${name} exited unexpectedly with code ${String(code)}`));
  });
  return child;
}

async function run(file, args, cwd = webRoot) {
  const child = spawn(file, args, { cwd, stdio: "inherit", windowsHide: true });
  const code = await new Promise((resolveExit) => child.once("exit", (value) => resolveExit(value ?? 1)));
  if (code !== 0) throw new Error(`${file} exited with code ${code}`);
}

async function waitFor(url, timeoutMs = 30_000) {
  console.log(`[real-e2e] waiting for ${url}`);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) {
        await response.body?.cancel();
        console.log(`[real-e2e] ready ${url}`);
        return;
      }
    } catch { /* service is still starting */ }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 200));
  }
  throw new Error(`health check timed out: ${url}`);
}

function stopChildren() {
  return Promise.all(children.map(async (child) => {
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
    if (await portIsOpen(port)) throw new Error(`port ${String(port)} is already in use; refusing to test an unknown service`);
  }
}

function shutdown(code) {
  if (cleanupPromise) return cleanupPromise;
  stopping = true;
  cleanupPromise = (async () => {
    await stopChildren();
    let serviceStillListening = false;
    for (const port of [8000, 4173]) {
      if (await portIsOpen(port)) {
        serviceStillListening = true;
        console.error(`[real-e2e] port ${String(port)} is still in use after cleanup`);
      }
    }
    process.exitCode = serviceStillListening ? 1 : code;
  })();
  return cleanupPromise;
}

process.once("SIGINT", () => { void shutdown(130); });
process.once("SIGTERM", () => { void shutdown(143); });

let exitCode = 1;
try {
  console.log("[real-e2e] building current production assets");
  await run(node, [vite, "build"]);
  await requireFreePorts();
  launchService("FastAPI", python, ["-m", "uvicorn", "parking_opt.api.app:app", "--app-dir", resolve(repoRoot, "src"), "--host", "127.0.0.1", "--port", "8000", "--http", "h11", "--log-level", "warning"]);
  launchService("Vite preview", node, [vite, "preview", "--host", "127.0.0.1", "--port", "4173", "--strictPort"]);
  await Promise.race([Promise.all([
    waitFor("http://127.0.0.1:8000/api/v2/health"),
    waitFor("http://127.0.0.1:4173"),
  ]), serviceFailure]);
  console.log("[real-e2e] services ready; starting Playwright");
  const runner = launch(node, [playwright, "test", "--config", config, ...process.argv.slice(2)]);
  exitCode = await Promise.race([
    new Promise((resolveExit) => runner.once("exit", (code) => resolveExit(code ?? 1))),
    serviceFailure.then(() => 1),
  ]);
} catch (error) {
  console.error(error);
} finally {
  await shutdown(exitCode);
}
