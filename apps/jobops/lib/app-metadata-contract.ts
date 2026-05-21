export type JobOpsAppMetadata = {
  appName: string;
  releaseChannel: string;
  environment: string;
  commit: string;
  fullCommit?: string;
  buildTime?: string;
};

export const FALLBACK_JOBOPS_APP_METADATA: JobOpsAppMetadata = {
  appName: "JobOps",
  releaseChannel: "alpha",
  environment: "dev",
  commit: "local"
};

export function formatJobOpsAppMetadata(metadata: JobOpsAppMetadata) {
  const parts = [
    `${metadata.appName} ${metadata.releaseChannel}`,
    metadata.environment,
    `build ${metadata.commit}`
  ];

  return parts.join(" · ");
}

export function formatJobOpsAppMetadataTitle(metadata: JobOpsAppMetadata) {
  const details = [
    `Commit: ${metadata.fullCommit || metadata.commit}`,
    metadata.buildTime ? `Build time: ${metadata.buildTime}` : undefined
  ].filter(Boolean);

  return details.join("\n") || undefined;
}
