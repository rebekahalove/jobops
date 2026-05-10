import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ProfilePage from "../app/profile/page";
import { createMockProfileDraft, emptyTargetRoleIntent } from "../lib/profile-intake";
import { ProfileWorkspace } from "./profile-workspace";

describe("Profile intake workspace", () => {
  it("renders the profile page", () => {
    const html = renderToStaticMarkup(<ProfilePage />);

    expect(html).toContain("Your structured profile powers JobOps.");
  });

  it("renders target role intent and resume intake sections", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Step 1");
    expect(html).toContain("Target role intent");
    expect(html).toContain("Step 2");
    expect(html).toContain("Resume intake");
    expect(html).toContain("Generate draft profile");
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

  it("returns applied AI clarifying questions from the mock extractor", () => {
    const draft = createMockProfileDraft("Python LLM product work", emptyTargetRoleIntent);
    const questionText = draft.clarifyingQuestions.map((question) => question.question).join(" ");

    expect(questionText).toContain("AI, automation, or agentic products");
    expect(questionText).toContain("evals");
    expect(questionText).toContain("production constraints");
    expect(questionText).toContain("repos, demos, case studies");
  });
});
