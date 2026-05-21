export type JobOpsAppMetadata = {
  appName: string;
  releaseChannel: string;
  environment: string;
  build: string;
  buildTime?: string;
};

export const FALLBACK_JOBOPS_APP_METADATA: JobOpsAppMetadata = {
  appName: "JobOps",
  releaseChannel: "alpha",
  environment: "dev",
  build: "local"
};

export function formatJobOpsAppMetadata(metadata: JobOpsAppMetadata) {
  const parts = [
    `${metadata.appName} ${metadata.releaseChannel}`,
    metadata.environment,
    `build ${metadata.build}`
  ];

  if (metadata.buildTime) {
    parts.push(`built ${metadata.buildTime}`);
  }

  return parts.join(" · ");
}
