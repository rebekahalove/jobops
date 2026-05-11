import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ProfilePage from "../app/profile/page";
import {
  createMockIntakeTurn,
  createMockProfileDraft,
  emptyTargetRoleIntent,
  initialProfilePrompt
} from "../lib/profile-intake";
import { ClarifyingQuestions, ProfileWorkspace } from "./profile-workspace";

describe("Profile intake workspace", () => {
  it("renders the profile page", () => {
    const html = renderToStaticMarkup(<ProfilePage />);

    expect(html).toContain("Build your JobOps profile through conversation.");
  });

  it("renders the conversation-first intake panel", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Conversation-first intake");
    expect(html).toContain(initialProfilePrompt);
    expect(html).toContain("Attach resume");
    expect(html).toContain("Send to mock agent");
    expect(html).toContain("paste your resume into this same chat");
    expect(html).not.toContain("Resume text for local mock extraction");
  });

  it("keeps structured fields as review/edit surfaces below chat", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Structured review");
    expect(html).toContain("Review &amp; verify profile data");
    expect(html).toContain("Review");
    expect(html).toContain("Needs verification");
    expect(html).toContain("Visibility");
    expect(html).toContain("Publication");
    expect(html).not.toContain("These fields are updated by the conversation and can be edited before verification.");
    expect(html).not.toContain("The status bar applies to the profile overall.");
    expect(html).not.toContain("Draft review queues");
    expect(html).not.toContain("Review section");
    expect(html).not.toContain("Human-approved facts");
    expect(html).not.toContain("Public facts");
    expect(html).not.toContain("Experience containers");
    expect(html).not.toContain("experience containers");
  });

  it("rolls lower sections into collapsible panels", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("aria-label=\"Expand What changed\"");
    expect(html).toContain("aria-label=\"Expand Review &amp; verify profile data\"");
    expect(html).toContain("aria-label=\"Expand Clarifying questions\"");
    expect(html).not.toContain("Target role intent");
    expect(html).not.toContain("No questions yet");
  });

  it("marks mock extracted facts as draft, resume-derived, and not verified", () => {
    const draft = createMockProfileDraft(
      "Applied AI Engineer using Python, FastAPI, LLM evals, monitoring, and customer workflows.",
      emptyTargetRoleIntent
    );

    expect(draft.facts.length).toBeGreaterThan(0);
    expect(draft.facts.every((fact) => fact.reviewStatus === "draft")).toBe(true);
    expect(draft.facts.every((fact) => fact.source === "resume_derived")).toBe(true);
    expect(draft.facts.every((fact) => fact.verificationStatus === "not_verified")).toBe(true);
    expect(draft.facts.every((fact) => fact.visibility === "private")).toBe(true);
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
    expect(turn.changeSummary.join(" ")).toContain("unverified");
  });

  it("treats resume text pasted into chat as resume-derived draft input", () => {
    const turn = createMockIntakeTurn({
      messageText: "Experience\nApplied AI Engineer\nPython FastAPI LLM evals monitoring customer workflows.",
      currentIntent: emptyTargetRoleIntent
    });

    expect(turn.draft.facts.length).toBeGreaterThan(0);
    expect(turn.draft.experienceSummaries.length).toBeGreaterThan(0);
    expect(turn.draft.facts.some((fact) => fact.source === "resume_derived")).toBe(true);
    expect(turn.agentMessage).toContain("kept every new claim unverified and private");
  });

  it("creates experience/project items from past-work statements in chat", () => {
    const turn = createMockIntakeTurn({
      messageText: "I built an LLM eval harness for customer support workflows using Python and monitoring.",
      currentIntent: emptyTargetRoleIntent
    });

    expect(turn.draft.experienceSummaries.length).toBeGreaterThan(0);
    expect(turn.draft.experienceSummaries.every((experience) => experience.source === "chat_derived")).toBe(true);
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
