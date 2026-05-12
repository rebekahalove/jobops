import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { basename, dirname, join, relative, resolve } from "node:path";
import type { ModelRequest, ModelResponse } from "@jobops/model-connector";
import type { ProfileIntakeApiRequest, ProfileIntakeOutput } from "./profile-intake-contract";

export const PROFILE_INTAKE_PROMPT_VERSION = "profile-intake-prompt-v1";
export const PROFILE_INTAKE_SCHEMA_VERSION = "profile-intake-output-v1";

export type ProfileIntakeArtifactOptions = {
  rootDir?: string;
  runId?: string;
  saveArtifacts?: boolean;
  saveRawText?: boolean;
};

export type ProfileIntakeInputMetrics = {
  existingDraftFactCount: number;
  existingExperienceAndProjectCount: number;
  existingSkillClaimCount: number;
  latestUserMessageLength: number;
};

export type ProfileIntakeRunMetadata = {
  createdAt: string;
  feature: "profile_intake";
  input: ProfileIntakeInputMetrics;
  latencyMs: number;
  model?: string;
  promptVersion: string;
  provider?: string;
  responseFinishReason?: string;
  runId: string;
  schemaName?: string;
  schemaVersion: string;
  status: "success" | "failure";
  task: string;
  validationIssueCount: number;
};

export type ProfileIntakeArtifactRun = {
  artifactPath?: string;
  enabled: boolean;
  runDir?: string;
  runId?: string;
  saveRawText: boolean;
  writeJson: (filename: string, value: unknown, options?: { rawText?: boolean }) => Promise<void>;
  writeText: (filename: string, value: string, options?: { rawText?: boolean }) => Promise<void>;
};

export function createProfileIntakeArtifactRun(options: ProfileIntakeArtifactOptions = {}): ProfileIntakeArtifactRun {
  const enabled = options.saveArtifacts === true;
  const saveRawText = options.saveRawText === true;
  const runId = enabled ? options.runId ?? createRunId() : undefined;
  const createdAt = new Date();
  const rootDir = options.rootDir ?? defaultProfileIntakeArtifactRoot();
  const runDir = enabled && runId ? join(rootDir, `${formatTimestamp(createdAt)}_${sanitizePathSegment(runId)}`) : undefined;
  const artifactPath = runDir ? relative(defaultRepoRoot(), runDir) || runDir : undefined;

  async function ensureRunDir() {
    if (runDir) {
      await mkdir(runDir, { recursive: true });
    }
  }

  return {
    artifactPath,
    enabled,
    runDir,
    runId,
    saveRawText,
    async writeJson(filename, value, writeOptions = {}) {
      if (!enabled || (writeOptions.rawText && !saveRawText)) {
        return;
      }

      await ensureRunDir();
      await writeFile(join(runDir!, filename), `${JSON.stringify(value, null, 2)}\n`, "utf-8");
    },
    async writeText(filename, value, writeOptions = {}) {
      if (!enabled || (writeOptions.rawText && !saveRawText)) {
        return;
      }

      await ensureRunDir();
      await writeFile(join(runDir!, filename), value, "utf-8");
    }
  };
}

export function buildProfileIntakeInputMetrics(input: ProfileIntakeApiRequest): ProfileIntakeInputMetrics {
  const draft = isRecord(input.existingDraft) ? input.existingDraft : {};

  return {
    latestUserMessageLength: input.latestUserMessage.length,
    existingDraftFactCount: arrayLength(draft.draftFacts) + arrayLength(draft.facts),
    existingSkillClaimCount: arrayLength(draft.skillClaims),
    existingExperienceAndProjectCount: arrayLength(draft.experienceAndProjects) + arrayLength(draft.experienceSummaries)
  };
}

export function buildProfileIntakeRequestMetadata(request: ModelRequest, inputMetrics: ProfileIntakeInputMetrics) {
  return {
    feature: "profile_intake",
    input: inputMetrics,
    maxOutputTokens: request.maxOutputTokens,
    messageCount: request.messages.length,
    messages: request.messages.map((message) => ({
      contentLength: message.content.length,
      role: message.role
    })),
    promptVersion: PROFILE_INTAKE_PROMPT_VERSION,
    responseFormat: {
      schemaName: request.responseFormat?.type === "json" ? request.responseFormat.schemaName : undefined,
      type: request.responseFormat?.type
    },
    schemaVersion: PROFILE_INTAKE_SCHEMA_VERSION,
    task: request.task,
    temperature: request.temperature
  };
}

export function buildProfileIntakeRunMetadata({
  inputMetrics,
  latencyMs,
  request,
  response,
  runId,
  status,
  validationIssueCount
}: {
  inputMetrics: ProfileIntakeInputMetrics;
  latencyMs: number;
  request: ModelRequest;
  response?: ModelResponse;
  runId: string;
  status: ProfileIntakeRunMetadata["status"];
  validationIssueCount: number;
}): ProfileIntakeRunMetadata {
  return {
    createdAt: new Date().toISOString(),
    feature: "profile_intake",
    input: inputMetrics,
    latencyMs,
    model: response?.model,
    promptVersion: PROFILE_INTAKE_PROMPT_VERSION,
    provider: response?.provider,
    responseFinishReason: response?.finishReason,
    runId,
    schemaName: request.responseFormat?.type === "json" ? request.responseFormat.schemaName : undefined,
    schemaVersion: PROFILE_INTAKE_SCHEMA_VERSION,
    status,
    task: request.task,
    validationIssueCount
  };
}

export function buildProfileIntakePromptArtifact(request: ModelRequest) {
  return request.messages.map((message) => `## ${message.role}\n\n${message.content}`).join("\n\n---\n\n");
}

export async function saveProfileIntakeSuccessArtifacts({
  artifacts,
  inputMetrics,
  latencyMs,
  output,
  request,
  response
}: {
  artifacts: ProfileIntakeArtifactRun;
  inputMetrics: ProfileIntakeInputMetrics;
  latencyMs: number;
  output: ProfileIntakeOutput;
  request: ModelRequest;
  response: ModelResponse;
}) {
  if (!artifacts.enabled || !artifacts.runId) {
    return;
  }

  await artifacts.writeJson("parsed-output.json", output, { rawText: true });
  await artifacts.writeJson(
    "metadata.json",
    buildProfileIntakeRunMetadata({
      inputMetrics,
      latencyMs,
      request,
      response,
      runId: artifacts.runId,
      status: "success",
      validationIssueCount: 0
    })
  );
}

export async function saveProfileIntakeFailureArtifacts({
  artifacts,
  inputMetrics,
  issues,
  latencyMs,
  request,
  response
}: {
  artifacts: ProfileIntakeArtifactRun;
  inputMetrics: ProfileIntakeInputMetrics;
  issues: string[];
  latencyMs: number;
  request: ModelRequest;
  response?: ModelResponse;
}) {
  if (!artifacts.enabled || !artifacts.runId) {
    return;
  }

  await artifacts.writeJson("validation-error.json", {
    feature: "profile_intake",
    issues,
    runId: artifacts.runId,
    validationIssueCount: issues.length
  });
  await artifacts.writeJson(
    "metadata.json",
    buildProfileIntakeRunMetadata({
      inputMetrics,
      latencyMs,
      request,
      response,
      runId: artifacts.runId,
      status: "failure",
      validationIssueCount: issues.length
    })
  );
}

function arrayLength(value: unknown) {
  return Array.isArray(value) ? value.length : 0;
}

function createRunId() {
  return randomUUID().slice(0, 8);
}

function defaultProfileIntakeArtifactRoot() {
  return join(defaultRepoRoot(), "artifacts", "profile-intake");
}

function defaultRepoRoot() {
  const cwd = process.cwd();
  return basename(cwd) === "jobops" && basename(dirname(cwd)) === "apps" ? resolve(cwd, "../..") : cwd;
}

function formatTimestamp(date: Date) {
  return date.toISOString().replace(/[-:.]/g, "").replace("T", "T").replace("Z", "Z");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sanitizePathSegment(value: string) {
  return value.replace(/[^A-Za-z0-9_-]/g, "_");
}
