import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ProfilePage from "../app/profile/page";
import {
  applyProfileIntakeOutputToState,
  createMockIntakeTurn,
  createMockProfileDraft,
  emptyTargetRoleIntent,
  initialProfilePrompt
} from "../lib/profile-intake";
import { ClarifyingQuestions, ProfileWorkspace } from "./profile-workspace";

describe("Profile intake workspace", () => {
  it("renders the profile page", () => {
    const html = renderToStaticMarkup(<ProfilePage />);

    expect(html).toContain("Review your JobOps profile draft.");
  });

  it("does not render a standalone chat composer", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Saved draft status");
    expect(html).not.toContain("Single command surface");
    expect(html).not.toContain(initialProfilePrompt);
    expect(html).not.toContain("Attach resume");
    expect(html).not.toContain("Send to intake agent");
    expect(html).not.toContain("Profile intake conversation");
    expect(html).not.toContain("chat-composer");
    expect(html).not.toContain("Resume text for local mock extraction");
  });

  it("keeps structured fields as review/edit surfaces", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Structured review");
    expect(html).toContain("Review &amp; verify profile data");
    expect(html).toContain("Target role intent");
    expect(html).toContain("Draft review queues");
    expect(html).toContain("Experience &amp; Projects");
    expect(html).toContain("Skills");
    expect(html).toContain("Evidence &amp; Links");
    expect(html).toContain("Review");
    expect(html).toContain("Needs verification");
    expect(html).toContain("Visibility");
    expect(html).toContain("Publication");
    expect(html).not.toContain("Review section");
    expect(html).not.toContain("Human-approved facts");
    expect(html).not.toContain("Public facts");
    expect(html).not.toContain("Experience containers");
    expect(html).not.toContain("experience containers");
  });

  it("keeps review sections in collapsible panels", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("aria-label=\"Collapse What changed\"");
    expect(html).toContain("aria-label=\"Collapse Review &amp; verify profile data\"");
    expect(html).toContain("aria-label=\"Collapse Clarifying questions\"");
    expect(html).toContain("Target role intent");
    expect(html).toContain("No questions yet");
  });

  it("points empty profile states to command-center intake instead of stale page chat copy", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Use the JobOps command center above to update your profile draft.");
    expect(html).toContain("Command-center profile intake will draft profile facts for review.");
    expect(html).toContain("Command-center profile intake should pull these answers forward over time.");
    expect(html).not.toContain("Send a message or attach a resume");
    expect(html).not.toContain("Use the conversation panel");
    expect(html).not.toContain("local summary");
  });

  it("marks mock extracted facts as draft, resume-derived, and not verified", () => {
    const draft = createMockProfileDraft(
      "Applied AI Engineer using Python, FastAPI, LLM evals, monitoring, and customer workflows.",
      emptyTargetRoleIntent
    );

    expect(draft.facts.length).toBeGreaterThan(0);
    expect(draft.facts.every((fact) => fact.status === "needs_review")).toBe(true);
    expect(draft.facts.every((fact) => fact.source === "resume")).toBe(true);
    expect(draft.facts.every((fact) => fact.visibility === "private")).toBe(true);
    expect(draft.facts.every((fact) => fact.published === false)).toBe(true);
  });

  it("derives target role intent without creating experience or claim drafts from target text", () => {
    const turn = createMockIntakeTurn({
      messageText: "I want to be an Applied AI Engineer working on remote LLM evals.",
      attachedResumeText: "",
      currentIntent: emptyTargetRoleIntent
    });

    expect(turn.intent.targetTitles).toBe("Applied AI Engineer working on remote LLM evals");
    expect(turn.intent.roleFamilies).toContain("LLM systems");
    expect(turn.intent.preferredWorkMode).toBe("remote");
    expect(turn.draft.facts).toHaveLength(0);
    expect(turn.draft.skillClaims).toHaveLength(0);
    expect(turn.draft.experienceSummaries).toHaveLength(0);
    expect(turn.changeSummary.join(" ")).toContain("needs review");
  });

  it("treats resume text pasted into chat as resume-derived draft input", () => {
    const turn = createMockIntakeTurn({
      messageText: "Experience\nApplied AI Engineer\nPython FastAPI LLM evals monitoring customer workflows.",
      currentIntent: emptyTargetRoleIntent
    });

    expect(turn.draft.facts.length).toBeGreaterThan(0);
    expect(turn.draft.experienceSummaries.length).toBeGreaterThan(0);
    expect(turn.draft.facts.some((fact) => fact.source === "resume")).toBe(true);
    expect(turn.agentMessage).toContain("kept every new claim private and marked needs review");
  });

  it("creates experience/project items from past-work statements in chat", () => {
    const turn = createMockIntakeTurn({
      messageText: "I built an LLM eval harness for customer support workflows using Python and monitoring.",
      currentIntent: emptyTargetRoleIntent
    });

    expect(turn.draft.experienceSummaries.length).toBeGreaterThan(0);
    expect(turn.draft.experienceSummaries.every((experience) => experience.source === "chat")).toBe(true);
  });

  it("applies model-assisted intake output to local draft review state", () => {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates and kept them private.",
      targetRoleIntent: {
        targetTitles: "Applied AI Engineer",
        targetRoleFamilies: "LLM systems"
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
          skill: "LLM evals",
          category: "ai_systems",
          evidence: "Unverified chat evidence.",
          source: "chat",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
      experienceAndProjects: [],
      evidenceLinks: [],
      clarifyingQuestions: ["What production constraints did you handle?"],
      changeSummary: ["Updated target role intent.", "Created one draft claim."]
    });

    expect(nextState.intent.targetTitles).toBe("Applied AI Engineer");
    expect(nextState.intent.roleFamilies).toBe("LLM systems");
    expect(nextState.draft.facts[0]).toMatchObject({
      source: "chat",
      status: "needs_review",
      visibility: "private",
      published: false
    });
    expect(nextState.turn.agentMessage).toBe("I drafted updates and kept them private.");
  });

  it("loads saved draft state from the profile-draft proxy", async () => {
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("./profile-workspace.tsx", import.meta.url), "utf-8");

    expect(source).toContain('fetch("/api/profile-draft"');
    expect(source).toContain('addEventListener("jobops:profile-draft-updated"');
    expect(source).not.toContain('fetch("/api/profile-intake"');
    expect(source).toContain("applyProfileIntakeOutputToState");
  });

  it("keeps the Next profile-intake route as a thin FastAPI proxy", async () => {
    const { readFile } = await import("node:fs/promises");
    const routeSource = await readFile(new URL("../app/api/profile-intake/route.ts", import.meta.url), "utf-8");

    expect(routeSource).toContain("/v1/profile-intake/extract");
    expect(routeSource).not.toContain("@jobops/model-connector");
    expect(routeSource).not.toContain("runProfileIntakeExtraction");
    expect(routeSource).not.toContain("buildProfileIntakeUserPrompt");
    expect(routeSource).not.toContain("generateProfileIntakeOutput");
    expect(routeSource).not.toContain("saveProfileIntake");
  });

  it("does not import server connector code into the client component", async () => {
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("./profile-workspace.tsx", import.meta.url), "utf-8");

    expect(source).not.toContain("@jobops/model-connector");
    expect(source).not.toContain("@jobops/model-connector/server");
  });

  it("renders clarifying questions as a compact list without per-question titles", () => {
    const draft = createMockProfileDraft("Experience\nApplied AI Engineer\nPython LLM product work", emptyTargetRoleIntent);
    const html = renderToStaticMarkup(<ClarifyingQuestions draft={draft} />);

    expect(html).toContain("Suggested next questions");
    expect(html).toContain("What AI, automation, or agentic products have you shipped beyond a prototype?");
    expect(html).not.toContain("Shipped AI products");
    expect(html).not.toContain("Evals and reliability");
  });

  it("returns applied AI clarifying questions from the mock extractor", () => {
    const draft = createMockProfileDraft("Python LLM product work", emptyTargetRoleIntent);
    const questionText = draft.clarifyingQuestions.map((question) => question.question).join(" ");

    expect(questionText).toContain("AI, automation, or agentic products");
    expect(questionText).toContain("evals");
    expect(questionText).toContain("production constraints");
    expect(questionText).toContain("repos, demos, case studies");
  });
});
