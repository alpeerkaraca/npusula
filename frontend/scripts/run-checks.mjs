import { spawnSync } from "node:child_process";
for (const args of [
  ["--test", "scripts/check-api.test.mjs"],
  ["scripts/check-ui.mjs"],
]) {
  const result = spawnSync(process.execPath, args, { stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
