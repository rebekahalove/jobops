import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = findRepoRoot(dirname(fileURLToPath(import.meta.url)));
loadEnvFile(join(repoRoot, ".env"));

const appEnv = process.env.APP_ENV;
if (appEnv && /^[A-Za-z0-9_-]+$/.test(appEnv)) {
  loadEnvFile(join(repoRoot, `.env.${appEnv}`));
}

const [command, ...args] = process.argv.slice(2);
if (!command) {
  console.error("Usage: node scripts/run-with-jobops-env.mjs <command> [...args]");
  process.exit(1);
}

const child = spawn(command, args, {
  env: process.env,
  shell: true,
  stdio: "inherit"
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exit(code ?? 0);
});

function findRepoRoot(startDir) {
  let current = startDir;

  while (current !== dirname(current)) {
    if (existsSync(join(current, "pnpm-workspace.yaml"))) {
      return current;
    }

    current = dirname(current);
  }

  throw new Error("Could not find JobOps repo root.");
}

function loadEnvFile(path) {
  if (!existsSync(path)) {
    return;
  }

  const contents = readFileSync(path, "utf8");
  for (const rawLine of contents.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }

    const separatorIndex = line.indexOf("=");
    if (separatorIndex === -1) {
      continue;
    }

    const key = line.slice(0, separatorIndex).trim();
    const value = unquoteEnvValue(line.slice(separatorIndex + 1).trim());
    if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function unquoteEnvValue(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }

  return value;
}
