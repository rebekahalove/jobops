import "server-only";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const APP_ENV_PATTERN = /^[A-Za-z0-9_-]+$/;

export async function getServerEnvValue(key: string) {
  const repoRoot = resolve(process.cwd(), "../..");
  const baseValues = await readDotenv(join(repoRoot, ".env"));
  const appEnv = process.env.APP_ENV ?? baseValues.APP_ENV ?? "dev";

  if (!APP_ENV_PATTERN.test(appEnv)) {
    throw new Error("APP_ENV must be a simple environment name.");
  }

  const environmentValues = await readDotenv(join(repoRoot, `.env.${appEnv}`));
  return process.env[key] ?? environmentValues[key] ?? baseValues[key];
}

async function readDotenv(path: string) {
  try {
    const content = await readFile(path, "utf-8");
    return parseDotenv(content);
  } catch {
    return {};
  }
}

function parseDotenv(content: string) {
  const values: Record<string, string> = {};

  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
      continue;
    }

    const [rawKey, ...rawValueParts] = trimmed.split("=");
    const key = rawKey.trim();
    const value = rawValueParts.join("=").trim().replace(/^["']|["']$/g, "");

    if (key) {
      values[key] = value;
    }
  }

  return values;
}
