import "server-only";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const APP_ENV_PATTERN = /^[A-Za-z0-9_-]+$/;

type JobOpsServerEnv = Record<string, string | undefined>;

export async function getJobOpsServerEnv(keys: string[]): Promise<JobOpsServerEnv> {
  const repoRoot = resolve(process.cwd(), "../..");
  const baseValues = await readDotenv(join(repoRoot, ".env"));
  const appEnv = process.env.APP_ENV ?? baseValues.APP_ENV ?? "dev";

  if (!APP_ENV_PATTERN.test(appEnv)) {
    throw new Error("APP_ENV must be a simple environment name.");
  }

  const environmentValues = await readDotenv(join(repoRoot, `.env.${appEnv}`));

  return Object.fromEntries(keys.map((key) => [key, process.env[key] ?? environmentValues[key] ?? baseValues[key]]));
}

export async function getJobOpsApiServerConfig(
  extraKeys: string[] = []
): Promise<JobOpsServerEnv & { apiBaseUrl: string; internalApiKey: string }> {
  const env = await getJobOpsServerEnv(["JOBOPS_API_BASE_URL", "JOBOPS_INTERNAL_API_KEY", ...extraKeys]);
  const internalApiKey = requireJobOpsServerEnvValue(env, "JOBOPS_INTERNAL_API_KEY");

  return {
    ...env,
    apiBaseUrl: env.JOBOPS_API_BASE_URL ?? "http://localhost:8000",
    internalApiKey
  };
}

export function requireJobOpsServerEnvValue(env: JobOpsServerEnv, key: string): string {
  const value = env[key]?.trim();
  if (!value) {
    throw new Error(`${key} is required for this JobOps server route.`);
  }
  return value;
}

async function readDotenv(path: string) {
  try {
    return parseDotenv(await readFile(path, "utf-8"));
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
