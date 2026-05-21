import "server-only";

import type { JobOpsAppMetadata } from "./app-metadata-contract";
import { FALLBACK_JOBOPS_APP_METADATA } from "./app-metadata-contract";

type Env = Record<string, string | undefined>;

const SAFE_LABEL_PATTERN = /^[A-Za-z0-9._-]+$/;
const SAFE_COMMIT_PATTERN = /^[A-Za-z0-9._-]+$/;

export function getJobOpsAppMetadata(env: Env = process.env): JobOpsAppMetadata {
  return {
    appName: FALLBACK_JOBOPS_APP_METADATA.appName,
    releaseChannel: safeLabel(firstValue(env.NEXT_PUBLIC_JOBOPS_RELEASE_CHANNEL, env.JOBOPS_RELEASE_CHANNEL), "alpha"),
    environment: resolveEnvironment(env),
    build: shortCommit(firstValue(
      env.NEXT_PUBLIC_JOBOPS_COMMIT_SHA,
      env.JOBOPS_COMMIT_SHA,
      env.COMMIT_REF,
      env.NETLIFY_COMMIT_REF,
      env.VERCEL_GIT_COMMIT_SHA,
      env.RENDER_GIT_COMMIT,
      env.GITHUB_SHA,
      env.CF_PAGES_COMMIT_SHA
    )),
    buildTime: safeBuildTime(firstValue(env.NEXT_PUBLIC_JOBOPS_BUILD_TIME, env.JOBOPS_BUILD_TIME, env.BUILD_TIME))
  };
}

function resolveEnvironment(env: Env) {
  const explicit = safeLabel(firstValue(env.NEXT_PUBLIC_JOBOPS_APP_ENV, env.JOBOPS_APP_ENV, env.APP_ENV), "");
  if (explicit) {
    return normalizeEnvironment(explicit);
  }

  const netlifyContext = safeLabel(firstValue(env.NETLIFY_CONTEXT, env.CONTEXT), "");
  if (netlifyContext) {
    return normalizeEnvironment(netlifyContext);
  }

  const vercelEnvironment = safeLabel(env.VERCEL_ENV, "");
  if (vercelEnvironment) {
    return normalizeEnvironment(vercelEnvironment);
  }

  return FALLBACK_JOBOPS_APP_METADATA.environment;
}

function normalizeEnvironment(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === "production") {
    return "prod";
  }
  if (normalized === "development" || normalized === "local") {
    return "dev";
  }
  if (normalized === "deploy-preview" || normalized === "branch-deploy") {
    return "preview";
  }

  return normalized || FALLBACK_JOBOPS_APP_METADATA.environment;
}

function shortCommit(value: string | undefined) {
  const normalized = value?.trim();
  if (!normalized || !SAFE_COMMIT_PATTERN.test(normalized)) {
    return FALLBACK_JOBOPS_APP_METADATA.build;
  }

  return normalized.slice(0, 7);
}

function safeBuildTime(value: string | undefined) {
  const normalized = value?.trim();
  if (!normalized) {
    return undefined;
  }

  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return undefined;
  }

  return new Date(parsed).toISOString();
}

function safeLabel(value: string | undefined, fallback: string) {
  const normalized = value?.trim();
  if (!normalized || !SAFE_LABEL_PATTERN.test(normalized)) {
    return fallback;
  }

  return normalized;
}

function firstValue(...values: Array<string | undefined>) {
  return values.find((value) => value?.trim());
}
