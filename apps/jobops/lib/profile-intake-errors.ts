import { StructuredOutputValidationError } from "@jobops/model-connector";

export class ProfileIntakeValidationError extends StructuredOutputValidationError {
  readonly artifactPath?: string;
  readonly debugRunId?: string;

  constructor(
    issues: string[],
    options: {
      artifactPath?: string;
      debugRunId?: string;
    } = {}
  ) {
    super(issues);
    this.name = "ProfileIntakeValidationError";
    this.artifactPath = options.artifactPath;
    this.debugRunId = options.debugRunId;
  }
}

export function getProfileIntakeDebugRunId(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "debugRunId" in error
    ? (error as { debugRunId?: string }).debugRunId
    : undefined;
}

export function getProfileIntakeArtifactPath(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "artifactPath" in error
    ? (error as { artifactPath?: string }).artifactPath
    : undefined;
}
