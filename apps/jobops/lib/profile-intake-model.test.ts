import { describe, expect, it } from "vitest";
import {
  createDefaultRoutingConfig,
  MockModelConnector,
  StructuredOutputValidationError
} from "@jobops/model-connector";
import { createProfileIntakeConnector, generateProfileIntakeOutput } from "./profile-intake-generator";

describe("profile intake model boundary", () => {
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
});
