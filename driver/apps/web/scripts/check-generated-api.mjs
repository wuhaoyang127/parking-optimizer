import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import process from "node:process";
import { URL } from "node:url";

const temporaryDirectory = mkdtempSync(join(tmpdir(), "parking-web-api-"));
const generatedPath = join(temporaryDirectory, "schema.d.ts");

try {
  const cli = join(process.cwd(), "node_modules", "openapi-typescript", "bin", "cli.js");
  execFileSync(process.execPath, [cli, "../../schemas/v2/openapi.json", "-o", generatedPath]);
  const committed = readFileSync(new URL("../src/api/schema.d.ts", import.meta.url), "utf8");
  const generated = readFileSync(generatedPath, "utf8");
  if (committed !== generated) {
    throw new Error("Generated API types are stale; run npm run generate:api");
  }
  process.stdout.write("Generated API types match schemas/v2/openapi.json\n");
} finally {
  rmSync(temporaryDirectory, { recursive: true, force: true });
}
