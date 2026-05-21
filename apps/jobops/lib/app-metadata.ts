import "server-only";

import { FALLBACK_JOBOPS_APP_METADATA, type JobOpsAppMetadata } from "./app-metadata-contract";
import { GENERATED_JOBOPS_BUILD_INFO } from "./generated-build-info";

const SAFE_LABEL_PATTERN = /^[A-Za-z0-9._-]+$/;
const SAFE_COMMIT_PATTERN = /^[A-Za-z0-9._-]+$/;

export function getJobOpsAppMetadata(): JobOpsAppMetadata {
  return {
    appName: "JobOps",
    releaseChannel: "alpha",
    environment: safeLabel(GENERATED_JOBOPS_BUILD_INFO.environment, FALLBACK_JOBOPS_APP_METADATA.environment),
    commit: shortCommit(GENERATED_JOBOPS_BUILD_INFO.commit || GENERATED_JOBOPS_BUILD_INFO.fullCommit),
    fullCommit: safeCommit(GENERATED_JOBOPS_BUILD_INFO.fullCommit || GENERATED_JOBOPS_BUILD_INFO.commit),
    buildTime: safeBuildTime(GENERATED_JOBOPS_BUILD_INFO.buildTime)
  };
}

function shortCommit(value: string | undefined) {
  const normalized = safeCommit(value);
  if (!normalized || normalized === "local") {
    return FALLBACK_JOBOPS_APP_METADATA.commit;
  }

  return normalized.slice(0, 7);
}

function safeCommit(value: string | undefined) {
  const normalized = value?.trim();
  if (!normalized || !SAFE_COMMIT_PATTERN.test(normalized)) {
    return undefined;
  }

  return normalized;
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
