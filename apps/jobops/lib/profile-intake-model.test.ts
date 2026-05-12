import { afterEach, describe, expect, it } from "vitest";
import {
  createDefaultRoutingConfig,
  MockModelConnector,
  StructuredOutputValidationError
} from "@jobops/model-connector";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createProfileIntakeConnector, generateProfileIntakeOutput } from "./profile-intake-generator";

const tempRoots: string[] = [];
const originalGeminiApiKey = process.env.GEMINI_API_KEY;

describe("profile intake model boundary", () => {
  afterEach(async () => {
    if (originalGeminiApiKey === undefined) {
      delete process.env.GEMINI_API_KEY;
    } else {
      process.env.GEMINI_API_KEY = originalGeminiApiKey;
    }

    await Promise.all(tempRoots.splice(0).map((path) => rm(path, { force: true, recursive: true })));
  });

  it("uses the mock provider to populate target role intent without live model calls", async () => {
    const connector = createProfileIntakeConnector({
      provider: "mock",
      defaultModel: "mock-default",
      cheapModel: "mock-cheap"
    });
    const output = await generateProfileIntakeOutput(connector, {
      latestUserMessage: "I want to be an Applied AI Engineer working on remote LLM systems."
    });

    expect(output.targetRoleIntent.targetTitles).toBe("Applied AI Engineer working on remote LLM systems");
    expect(output.targetRoleIntent.targetRoleFamilies).toContain("LLM systems");
    expect(output.targetRoleIntent.preferredWorkMode).toBe("remote");
    expect(output.draftFacts).toHaveLength(0);
    expect(output.experienceAndProjects).toHaveLength(0);
  });

  it("keeps generated data draft, private, and unpublished when mock input contains work history", async () => {
    const connector = createProfileIntakeConnector({
      provider: "mock",
      defaultModel: "mock-default",
      cheapModel: "mock-cheap"
    });
    const output = await generateProfileIntakeOutput(connector, {
      latestUserMessage:
        "Experience\nApplied AI Engineer\nI built an LLM eval harness with Python, FastAPI, monitoring, and Postgres."
    });
    const generatedItems = [...output.draftFacts, ...output.skillClaims, ...output.experienceAndProjects];

    expect(generatedItems.length).toBeGreaterThan(0);
    expect(generatedItems.every((item) => item.status === "needs_review")).toBe(true);
    expect(generatedItems.every((item) => item.visibility === "private")).toBe(true);
    expect(generatedItems.every((item) => item.published === false)).toBe(true);
  });

  it("rejects malformed model output before it can update draft state", async () => {
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      defaultResponse: JSON.stringify({
        assistantMessage: "Bad output.",
        targetRoleIntent: {},
        draftFacts: [
          {
            claim: "Unsafe publication attempt.",
            source: "chat",
            status: "verified",
            visibility: "public",
            published: true
          }
        ],
        skillClaims: [],
        experienceAndProjects: [],
        evidenceLinks: [],
        clarifyingQuestions: [],
        changeSummary: []
      })
    });

    await expect(
      generateProfileIntakeOutput(connector, {
        latestUserMessage: "I built an eval harness."
      })
    ).rejects.toBeInstanceOf(StructuredOutputValidationError);
  });

  it("does not write artifacts by default", async () => {
    const artifactRoot = await createTempArtifactRoot();
    const connector = createProfileIntakeConnector({
      provider: "mock",
      defaultModel: "mock-default",
      cheapModel: "mock-cheap"
    });

    await generateProfileIntakeOutput(
      connector,
      {
        latestUserMessage: "I built a Python API."
      },
      {
        artifacts: {
          rootDir: artifactRoot,
          saveArtifacts: false,
          saveRawText: false
        }
      }
    );

    await expect(readdir(artifactRoot)).resolves.toEqual([]);
  });

  it("writes metadata artifacts without raw prompt or response when enabled", async () => {
    const artifactRoot = await createTempArtifactRoot();
    const connector = createProfileIntakeConnector({
      provider: "mock",
      defaultModel: "mock-default",
      cheapModel: "mock-cheap"
    });

    await generateProfileIntakeOutput(
      connector,
      {
        latestUserMessage: "Experience\nApplied AI Engineer\nI built a Python API.",
        existingDraft: {
          facts: [{ claim: "Existing draft fact" }],
          skillClaims: [{ skill: "Python" }],
          experienceSummaries: [{ title: "Existing project" }]
        }
      },
      {
        artifacts: {
          rootDir: artifactRoot,
          runId: "metadata-test",
          saveArtifacts: true,
          saveRawText: false
        }
      }
    );

    const runDir = await onlyRunDir(artifactRoot);
    const files = await readdir(runDir);
    const metadata = JSON.parse(await readFile(join(runDir, "metadata.json"), "utf-8")) as {
      input: {
        existingDraftFactCount: number;
        existingExperienceAndProjectCount: number;
        existingSkillClaimCount: number;
        latestUserMessageLength: number;
      };
      provider: string;
      status: string;
    };

    expect(files).toEqual(expect.arrayContaining(["metadata.json", "request-metadata.json"]));
    expect(files).not.toContain("prompt.txt");
    expect(files).not.toContain("raw-response.txt");
    expect(files).not.toContain("parsed-output.json");
    expect(metadata.status).toBe("success");
    expect(metadata.provider).toBe("mock");
    expect(metadata.input.existingDraftFactCount).toBe(1);
    expect(metadata.input.existingSkillClaimCount).toBe(1);
    expect(metadata.input.existingExperienceAndProjectCount).toBe(1);
    expect(metadata.input.latestUserMessageLength).toBeGreaterThan(0);
  });

  it("writes raw prompt and response artifacts only when raw text saving is enabled", async () => {
    const artifactRoot = await createTempArtifactRoot();
    const connector = createProfileIntakeConnector({
      provider: "mock",
      defaultModel: "mock-default",
      cheapModel: "mock-cheap"
    });

    await generateProfileIntakeOutput(
      connector,
      {
        latestUserMessage: "Experience\nApplied AI Engineer\nI built a Python API."
      },
      {
        artifacts: {
          rootDir: artifactRoot,
          runId: "raw-test",
          saveArtifacts: true,
          saveRawText: true
        }
      }
    );

    const runDir = await onlyRunDir(artifactRoot);
    const files = await readdir(runDir);

    expect(files).toEqual(
      expect.arrayContaining(["metadata.json", "parsed-output.json", "prompt.txt", "raw-response.txt"])
    );
    await expect(readFile(join(runDir, "prompt.txt"), "utf-8")).resolves.toContain("latestUserMessage");
    await expect(readFile(join(runDir, "raw-response.txt"), "utf-8")).resolves.toContain("assistantMessage");
  });

  it("writes validation-error.json when validation fails", async () => {
    const artifactRoot = await createTempArtifactRoot();
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      defaultResponse: "not json"
    });

    await expect(
      generateProfileIntakeOutput(
        connector,
        {
          latestUserMessage: "I built an eval harness."
        },
        {
          artifacts: {
            rootDir: artifactRoot,
            runId: "failure-test",
            saveArtifacts: true,
            saveRawText: false
          }
        }
      )
    ).rejects.toMatchObject({
      debugRunId: "failure-test"
    });

    const runDir = await onlyRunDir(artifactRoot);
    const files = await readdir(runDir);
    const validationError = JSON.parse(await readFile(join(runDir, "validation-error.json"), "utf-8")) as {
      issues: string[];
      runId: string;
    };

    expect(files).toEqual(expect.arrayContaining(["metadata.json", "request-metadata.json", "validation-error.json"]));
    expect(validationError.runId).toBe("failure-test");
    expect(validationError.issues).toContain("Output is not valid JSON.");
    expect(files).not.toContain("raw-response.txt");
  });

  it("does not write API keys or secret env values to artifacts", async () => {
    const artifactRoot = await createTempArtifactRoot();
    const secret = "test-secret-gemini-key";
    process.env.GEMINI_API_KEY = secret;
    const connector = createProfileIntakeConnector({
      provider: "mock",
      defaultModel: "mock-default",
      cheapModel: "mock-cheap",
      geminiApiKey: secret
    });

    await generateProfileIntakeOutput(
      connector,
      {
        latestUserMessage: "Experience\nApplied AI Engineer\nI built a Python API."
      },
      {
        artifacts: {
          rootDir: artifactRoot,
          runId: "secret-test",
          saveArtifacts: true,
          saveRawText: true
        }
      }
    );

    const runDir = await onlyRunDir(artifactRoot);
    const files = await readdir(runDir);
    const contents = await Promise.all(files.map((file) => readFile(join(runDir, file), "utf-8")));

    expect(contents.join("\n")).not.toContain(secret);
  });
});

async function createTempArtifactRoot() {
  const root = await mkdtemp(join(tmpdir(), "jobops-profile-intake-artifacts-"));
  tempRoots.push(root);
  return root;
}

async function onlyRunDir(root: string) {
  const entries = await readdir(root);
  expect(entries).toHaveLength(1);
  return join(root, entries[0]);
}
