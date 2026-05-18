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
import { ClarifyingQuestions, ProfileWorkspace, ReviewTabbedList } from "./profile-workspace";

describe("Profile intake workspace", () => {
  it("renders the profile page", () => {
    const html = renderToStaticMarkup(<ProfilePage />);

    expect(html).toContain("Review your JobOps profile draft.");
  });

  it("does not render a standalone chat composer", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

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
    expect(html).toContain("Review your JobOps profile draft.");
    expect(html).toContain("Targets");
    expect(html).toContain("Current Draft");
    expect(html).toContain("Current published profile");
    expect(html).toContain("Experience &amp; Projects");
    expect(html).toContain("Skills");
    expect(html).toContain("Achievements &amp; Outcomes");
    expect(html).toContain("Facts &amp; Claims");
    expect(html).toContain("Evidence &amp; Links");
    expect(html).toContain("Education");
    expect(html).toContain("Certifications");
    expect(html).toContain("aria-orientation=\"vertical\"");
    expect(html).toContain("aria-label=\"Needs verification\"");
    expect(html).toContain("title=\"Private\"");
    expect(html).toContain("title=\"Not published\"");
    expect(html).toContain("title=\"Agent draft\"");
    expect(html).not.toContain("Review section");
    expect(html).not.toContain("Human-approved facts");
    expect(html).not.toContain("Public facts");
    expect(html).not.toContain("Experience containers");
    expect(html).not.toContain("experience containers");
    expect(html).not.toContain("Latest profile intake");
    expect(html).not.toContain("Draft review queues");
    expect(html).not.toContain("<p class=\"eyebrow\">Profile workspace</p>");
    expect(html).not.toContain("Review &amp; verify profile data");
  });

  it("keeps review sections in collapsible panels", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("aria-label=\"Collapse What changed\"");
    expect(html).toContain("aria-label=\"Collapse Review your JobOps profile draft.\"");
    expect(html).toContain("aria-label=\"Collapse Clarifying questions\"");
    expect(html).toContain("Targets");
    expect(html).toContain("No questions yet");
  });

  it("points empty profile states to command-center intake instead of stale page chat copy", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Use the JobOps command center above to update your profile draft.");
    expect(html).toContain("No experience &amp; projects drafted yet.");
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
          yearsMin: 2,
          yearsMax: 4,
          source: "chat",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
      experienceAndProjects: [
        {
          itemType: "experience",
          title: "Applied AI Systems Engineer",
          organization: "Shadow Network Intelligence",
          startDate: "2024",
          endDate: "Present",
          location: "Remote",
          summary: "Built production AI reporting systems.",
          bullets: ["Reduced report generation from a workday to under 30 minutes."],
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
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
    expect(nextState.draft.skillClaims[0].yearsMin).toBe(2);
    expect(nextState.draft.skillClaims[0].yearsMax).toBe(4);
    expect(nextState.draft.experienceSummaries[0]).toMatchObject({
      itemType: "experience",
      startDate: "2024",
      endDate: "Present",
      location: "Remote",
      bullets: ["Reduced report generation from a workday to under 30 minutes."]
    });
    expect(nextState.turn.agentMessage).toBe("I drafted updates and kept them private.");
  });

  it("renders experience dates as separate from and to fields with location", () => {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates and kept them private.",
      targetRoleIntent: {},
      draftFacts: [],
      skillClaims: [],
      experienceAndProjects: [
        {
          itemType: "experience",
          title: "Applied AI Systems Engineer",
          organization: "Shadow Network Intelligence",
          startDate: "Jan 2024",
          endDate: "Present",
          location: "Remote - Louisville, KY",
          summary: "Built production AI reporting systems.",
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
      evidenceLinks: [],
      clarifyingQuestions: [],
      changeSummary: []
    });

    const html = renderToStaticMarkup(
      <ReviewTabbedList activeTab="experience" draft={nextState.draft} onTabChange={() => undefined} />
    );

    expect(html).toContain("From");
    expect(html).toContain("Jan 2024");
    expect(html).toContain("To");
    expect(html).toContain("Present");
    expect(html).toContain("Location");
    expect(html).toContain("Remote - Louisville, KY");
    expect(html).toContain("Type: experience");
    expect(html).not.toContain("<dt>Type</dt>");
  });

  it("shows review placeholders for missing experience dates and location", () => {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates and kept them private.",
      targetRoleIntent: {},
      draftFacts: [],
      skillClaims: [],
      experienceAndProjects: [
        {
          itemType: "project",
          title: "AI Reporting Platform",
          organization: "Shadow Network Intelligence",
          summary: "Built production AI reporting systems.",
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
      evidenceLinks: [],
      clarifyingQuestions: [],
      changeSummary: []
    });

    const html = renderToStaticMarkup(
      <ReviewTabbedList activeTab="experience" draft={nextState.draft} onTabChange={() => undefined} />
    );

    expect(html).toContain("From");
    expect(html).toContain("To");
    expect(html).toContain("Location");
    expect(html.match(/Needs review/g)?.length).toBeGreaterThanOrEqual(3);
    expect(html).toContain("Type: project");
  });

  it("shows education and certification rows only when they are structured with matching item types", () => {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates and kept them private.",
      targetRoleIntent: {},
      draftFacts: [],
      skillClaims: [],
      experienceAndProjects: [
        {
          itemType: "education",
          title: "B.A., Fine Arts",
          organization: "Indiana University",
          summary: "Degree listed in resume education section.",
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        },
        {
          itemType: "certification",
          title: "Certificate - Supervised Machine Learning",
          organization: "Stanford Online (Coursera)",
          summary: "Credential listed in resume certification section.",
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
      evidenceLinks: [],
      clarifyingQuestions: [],
      changeSummary: []
    });

    const educationHtml = renderToStaticMarkup(
      <ReviewTabbedList activeTab="education" draft={nextState.draft} onTabChange={() => undefined} />
    );
    const certificationHtml = renderToStaticMarkup(
      <ReviewTabbedList activeTab="certifications" draft={nextState.draft} onTabChange={() => undefined} />
    );

    expect(educationHtml).toContain("B.A., Fine Arts");
    expect(educationHtml).toContain("Indiana University");
    expect(educationHtml).not.toContain("<dt>Type</dt>");
    expect(certificationHtml).toContain("Certificate - Supervised Machine Learning");
    expect(certificationHtml).toContain("Stanford Online (Coursera)");
    expect(certificationHtml).not.toContain("<dt>Type</dt>");
  });

  it("does not reroute credential-like facts into education and certification tabs", () => {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates and kept them private.",
      targetRoleIntent: {},
      draftFacts: [
        {
          claim: "B.A., Fine Arts - Indiana University.",
          category: "education",
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        },
        {
          claim: "Certificate - Stanford Online (Coursera) - Supervised Machine Learning.",
          category: "certification",
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        },
        {
          claim: "Built a production AI reporting platform.",
          category: "ai_product",
          source: "resume",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
      skillClaims: [],
      experienceAndProjects: [],
      evidenceLinks: [],
      clarifyingQuestions: [],
      changeSummary: []
    });

    const educationHtml = renderToStaticMarkup(
      <ReviewTabbedList activeTab="education" draft={nextState.draft} onTabChange={() => undefined} />
    );
    const certificationHtml = renderToStaticMarkup(
      <ReviewTabbedList activeTab="certifications" draft={nextState.draft} onTabChange={() => undefined} />
    );
    const factsHtml = renderToStaticMarkup(
      <ReviewTabbedList activeTab="facts" draft={nextState.draft} onTabChange={() => undefined} />
    );

    expect(educationHtml).not.toContain("B.A., Fine Arts - Indiana University.");
    expect(certificationHtml).not.toContain("Certificate - Stanford Online (Coursera)");
    expect(factsHtml).toContain("Built a production AI reporting platform.");
    expect(factsHtml).toContain("B.A., Fine Arts - Indiana University.");
    expect(factsHtml).toContain("Certificate - Stanford Online (Coursera)");
  });

  it("loads saved draft state from the profile-draft proxy", async () => {
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("./profile-workspace.tsx", import.meta.url), "utf-8");

    expect(source).toContain('apiBasePath = "/api"');
    expect(source).toContain('fetch(`${apiBasePath}/profile-draft`)');
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
