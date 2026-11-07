import { spawn } from "node:child_process";
import { createServer, request } from "node:http";
import { createConnection } from "node:net";
import { resolve } from "node:path";

const webRoot = resolve(import.meta.dirname, "..");
const runnerPath = resolve(import.meta.dirname, "run-real-e2e.mjs");
const demoPath = resolve(import.meta.dirname, "start-web-v2.mjs");

function spawnScript(path) {
  return spawn(process.execPath, [path], { cwd: webRoot, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
}

function exitCode(child) {
  return new Promise((resolveExit) => child.once("exit", (code) => resolveExit(code ?? 1)));
}

function portOpen(port) {
  return new Promise((resolvePort) => {
    const socket = createConnection({ host: "127.0.0.1", port });
    socket.once("connect", () => { socket.destroy(); resolvePort(true); });
    socket.once("error", () => resolvePort(false));
  });
}

const occupied = createServer((_request, response) => response.end("occupied"));
await new Promise((resolveListen) => occupied.listen(8000, "127.0.0.1", resolveListen));
const conflictRunner = spawnScript(runnerPath);
const conflictCode = await exitCode(conflictRunner);
await new Promise((resolveClose) => occupied.close(resolveClose));
if (conflictCode === 0) throw new Error("occupied-port probe unexpectedly succeeded");

const demo = spawnScript(demoPath);
let output = "";
demo.stdout.on("data", (chunk) => { output += String(chunk); });
demo.stderr.on("data", (chunk) => { output += String(chunk); });
const deadline = Date.now() + 30_000;
while (!output.includes("[web-v2] ready:") && Date.now() < deadline) {
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
}
if (!output.includes("[web-v2] ready:")) {
  demo.kill("SIGKILL");
  throw new Error(`demo did not become ready: ${output}`);
}
demo.kill("SIGINT");
await exitCode(demo);
await new Promise((resolveDelay) => setTimeout(resolveDelay, 300));
if (await portOpen(8000) || await portOpen(4173)) throw new Error("ports remained occupied after demo interruption");

await new Promise((resolveProbe, rejectProbe) => {
  const probe = request("http://127.0.0.1:8000/api/v2/health", rejectProbe);
  probe.once("error", () => resolveProbe());
  probe.end();
});
console.log("ORCHESTRATION_PROBES_OK");
