import { describe, expect, it } from "vitest";
import { validateProfileIntakeOutput } from "./profile-intake-contract";

const validOutput = {
  assistantMessage: "I drafted profile updates and kept them private.",
  targetRoleIntent: {
    targetTitles: "Applied AI Engineer",
    targetRoleFamilies: "LLM systems",
    preferredWorkMode: "remote",
    preferredLocations: "Remote US",
    domainsOrIndustries: "developer tools",
    constraints: "No heavy travel."
  },
  draftFacts: [
    {
      claim: "Built an LLM eval harness.",
      category: "evals",
      source: "chat",
      status: "needs_review",
      visibility: "private",
      published: false
    }
  ],
  skillClaims: [
    {
      skill: "Python",
      category: "programming",
      evidence: "Mentioned in unverified intake text.",
      source: "resume",
      status: "draft",
      visibility: "private",
      published: false
    }
  ],
  experienceAndProjects: [
    {
      title: "Applied AI project",
      organization: "Needs review",
      summary: "Potential project evidence.",
      source: "chat",
      status: "needs_review",
      visibility: "private",
      published: false
    }
  ],
  evidenceLinks: [
    {
      url: "https://example.com/demo",
      label: "Demo",
      source: "resume",
      status: "needs_review",
      visibility: "private",
      published: false
    }
  ],
  clarifyingQuestions: ["What production constraints did you handle?"],
  changeSummary: ["Updated target role intent."]
};

describe("profile intake contract", () => {
  it("accepts valid profile intake model output", () => {
    const result = validateProfileIntakeOutput(validOutput);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.draftFacts[0].published).toBe(false);
    }
  });

  it("rejects malformed or unsafe profile intake output", () => {
    const result = validateProfileIntakeOutput({
      ...validOutput,
      draftFacts: [
        {
          claim: "This should not pass.",
          source: "chat",
          status: "verified",
          visibility: "public",
          published: true
        }
      ]
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.issues.join(" ")).toContain("draftFacts[0].status");
      expect(result.issues.join(" ")).toContain("draftFacts[0].visibility");
      expect(result.issues.join(" ")).toContain("draftFacts[0].published");
    }
  });

  it("rejects runaway target title expansion", () => {
    const result = validateProfileIntakeOutput({
      ...validOutput,
      targetRoleIntent: {
        targetTitles: Array.from({ length: 30 }, (_, index) => `Invented Adjacent Title ${index + 1}`).join(", ")
      }
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.issues).toContain("targetRoleIntent.targetTitles must be 200 characters or fewer.");
    }
  });

  it("rejects oversized arrays before applying draft output", () => {
    const result = validateProfileIntakeOutput({
      ...validOutput,
      skillClaims: Array.from({ length: 7 }, (_, index) => ({
        skill: `Skill ${index + 1}`,
        source: "resume",
        status: "needs_review",
        visibility: "private",
        published: false
      }))
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.issues).toContain("skillClaims must contain at most 6 item(s).");
    }
  });
});
