import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import ProfilePage from "../app/profile/page";
import { PublicPortfolio } from "../../portfolio/components/public-portfolio";
import {
  applyProfileIntakeOutputToState,
  createMockIntakeTurn,
  createMockProfileDraft,
  emptyTargetRoleIntent,
  initialProfilePrompt
} from "../lib/profile-intake";
import { ClarifyingQuestions, ProfileWorkspace, PublicPortfolioPreview, ReviewTabbedList } from "./profile-workspace";

describe("Profile intake workspace", () => {
  it("renders the profile page", () => {
    const html = renderToStaticMarkup(<ProfilePage />);

    expect(html).toContain("Review and publish profile knowledge.");
  });

  it("uses the shared full-width workspace shell for command center pages", () => {
    const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

    expect(css).toContain("--workspace-width: min(100% - 24px, 1680px)");
    expect(css).toContain("width: var(--workspace-width)");
    expect(css).toContain("position: fixed");
    expect(css).toContain("@keyframes profile-toast-slide");
    expect(css).toContain(".profile-header-recent");
    expect(css).toContain("grid-template-columns: 1fr");
    expect(css).not.toContain("profile-basics-tab");
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

    expect(html).toContain("Profile workspace");
    expect(html).toContain("Review and publish profile knowledge.");
    expect(html).toContain("Generated");
    expect(html).toContain("Private");
    expect(html).not.toContain("Archived</span>");
    expect(html).not.toContain("Internal JobOps context");
    expect(html).toContain("Public portfolio preview");
    expect(html).toContain("Private");
    expect(html).toContain("Targets");
    expect(html).toContain("Profile basics");
    expect(html).toContain("Experience &amp; Projects");
    expect(html).toContain("Skills");
    expect(html).toContain("Achievements &amp; Outcomes");
    expect(html).toContain("Facts &amp; Claims");
    expect(html).toContain("Evidence &amp; Links");
    expect(html).toContain("Education");
    expect(html).toContain("Certifications");
    expect(html).toContain("aria-orientation=\"vertical\"");
    expect(html).toContain("Profile section navigation");
    expect(html).not.toContain("Review section");
    expect(html).not.toContain("Human-approved facts");
    expect(html).not.toContain("Public facts");
    expect(html).not.toContain("Experience containers");
    expect(html).not.toContain("experience containers");
    expect(html).not.toContain("Latest profile intake");
    expect(html).not.toContain("Draft review queues");
    expect(html).not.toContain("Review &amp; verify profile data");
  });

  it("keeps profile review and context summaries visible without nested collapsible panels", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Recent changes");
    expect(html).toContain("Follow-up queue");
    expect(html).not.toContain("Published knowledge active internally");
    expect(html).not.toContain("aria-label=\"Collapse What changed\"");
    expect(html).toContain("Targets");
    expect(html).toContain("No questions yet");
  });

  it("points empty profile states to command-center intake instead of stale page chat copy", () => {
    const html = renderToStaticMarkup(<ProfileWorkspace />);

    expect(html).toContain("Use the JobOps command center above to update your generated profile items.");
    expect(html).toContain("Generated items are pending review");
    expect(html).toContain("Follow-up queue");
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

  it("labels generated lifecycle actions as publish private, publish public, and archive", () => {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates and kept them private.",
      targetRoleIntent: {},
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
      skillClaims: [],
      experienceAndProjects: [],
      evidenceLinks: [],
      clarifyingQuestions: [],
      changeSummary: []
    });

    const html = renderToStaticMarkup(
      <ReviewTabbedList activeLifecycle="generated" activeTab="facts" draft={nextState.draft} onTabChange={() => undefined} />
    );

    expect(html).toContain("Publish private");
    expect(html).toContain("Publish public");
    expect(html).toContain("Archive");
    expect(html).not.toContain("Reject");
    expect(html).not.toContain(">Approve<");
  });

  it("uses consistent generated and edited status icons", () => {
    const generatedState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates.",
      targetRoleIntent: {},
      draftFacts: [
        {
          claim: "Generated fact.",
          category: "impact",
          source: "chat",
          status: "needs_review",
          visibility: "private",
          published: false
        },
        {
          claim: "Edited fact.",
          category: "impact",
          source: "chat",
          status: "candidate_approved",
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

    const html = renderToStaticMarkup(
      <ReviewTabbedList activeLifecycle="generated" activeTab="facts" draft={generatedState.draft} onTabChange={() => undefined} />
    );

    expect(html).toContain("aria-label=\"Generated\"");
    expect(html).toContain("aria-label=\"Edited\"");
    expect(html).not.toContain("Needs review");
    expect(html).not.toContain("Edited by you");
  });

  it("renders target fields with field-level generated publish and archive actions", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="generated"
        activeTab="targets"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [],
          targets: [
            {
              group: "targets",
              name: "targetTitles",
              label: "Target titles",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: {
                id: "target-field-1",
                value: "Applied AI Engineer",
                source: "model",
                lifecycleStatus: "generated",
                visibility: null
              },
              published: null,
              archived: []
            }
          ]
        }}
      />
    );

    expect(html).toContain("Publish public");
    expect(html).toContain("Publish private");
    expect(html).toContain("Archive");
    expect(html).toContain("Applied AI Engineer");
  });

  it("does not render empty field definitions as generated proposals", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="generated"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "headline",
              label: "Headline",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: null,
              archived: []
            }
          ],
          targets: []
        }}
      />
    );

    expect(html).toContain("No generated field proposals yet.");
    expect(html).not.toContain("Publish private");
    expect(html).not.toContain("Headline");
  });

  it("does not render empty field definitions on the Private tab", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="private"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "headline",
              label: "Headline",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: null,
              archived: []
            }
          ],
          targets: []
        }}
      />
    );

    expect(html).toContain("No private field values in this section.");
    expect(html).not.toContain("Headline");
    expect(html).not.toContain("<input");
    expect(html).not.toContain("Make public");
    expect(html).not.toContain(">Archive</button>");
  });

  it("renders private field rows with Make public, not Make private, when public is allowed", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="private"
        activeTab="targets"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [],
          targets: [
            {
              group: "targets",
              name: "targetTitles",
              label: "Target titles",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: {
                id: "target-field-1",
                value: "Applied AI Engineer",
                source: "user",
                lifecycleStatus: "published",
                visibility: "private"
              },
              archived: []
            }
          ]
        }}
      />
    );

    expect(html).toContain("Make public");
    expect(html).toContain("Archive");
    expect(html).not.toContain("Make private");
    expect(html).toContain("Applied AI Engineer");
  });

  it("shows generated, private, and public counts in section headers and rail tabs", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="generated"
        activeTab="targets"
        draft={null}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [],
          targets: [
            {
              group: "targets",
              name: "targetTitles",
              label: "Target titles",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: {
                id: "target-generated",
                value: "Applied AI Engineer",
                source: "model",
                lifecycleStatus: "generated",
                visibility: null
              },
              published: null,
              archived: []
            },
            {
              group: "targets",
              name: "roleFamilies",
              label: "Target role families",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: {
                id: "target-private",
                value: "AI systems",
                source: "user",
                lifecycleStatus: "published",
                visibility: "private"
              },
              archived: []
            },
            {
              group: "targets",
              name: "preferredWorkMode",
              label: "Preferred work mode",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: {
                id: "target-public",
                value: "Remote",
                source: "user",
                lifecycleStatus: "published",
                visibility: "public"
              },
              archived: []
            }
          ]
        }}
      />
    );

    expect(html).toContain("1 Generated / 1 Private / 1 Public");
    expect(html).toContain("aria-label=\"1 Generated, 1 Private, 1 Public\"");
  });

  it("renders private-only field rows with Archive only on the Private tab", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="private"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "mailingAddress",
              label: "Mailing address",
              publicAllowed: false,
              privateOnly: true,
              multiline: true,
              generated: null,
              published: {
                id: "mailing-field-1",
                value: "123 Private Street",
                source: "user",
                lifecycleStatus: "published",
                visibility: "private"
              },
              archived: []
            }
          ],
          targets: []
        }}
      />
    );

    expect(html).toContain("Private only");
    expect(html).toContain("Archive");
    expect(html).not.toContain("Make public");
    expect(html).not.toContain("Make private");
  });

  it("keeps public field rows out of the Private tab", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="private"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "headline",
              label: "Headline",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: {
                id: "headline-field-1",
                value: "Public headline",
                source: "user",
                lifecycleStatus: "published",
                visibility: "public"
              },
              archived: []
            }
          ],
          targets: []
        }}
      />
    );

    expect(html).not.toContain("Public headline");
    expect(html).not.toContain("Make private");
    expect(html).toContain("Public values are managed in the preview");
  });

  it("renders generated public and private-only fields with the allowed action map", () => {
    const publicAllowedHtml = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="generated"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "headline",
              label: "Headline",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: {
                id: "headline-generated",
                value: "Generated headline",
                source: "model",
                lifecycleStatus: "generated",
                visibility: null
              },
              published: null,
              archived: []
            }
          ],
          targets: []
        }}
      />
    );
    const privateOnlyHtml = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="generated"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "mailingAddress",
              label: "Mailing address",
              publicAllowed: false,
              privateOnly: true,
              multiline: true,
              generated: {
                id: "mailing-generated",
                value: "Generated address",
                source: "model",
                lifecycleStatus: "generated",
                visibility: null
              },
              published: null,
              archived: []
            }
          ],
          targets: []
        }}
      />
    );

    expect(publicAllowedHtml).toContain("Publish private");
    expect(publicAllowedHtml).toContain("Publish public");
    expect(publicAllowedHtml).toContain("Archive");
    expect(privateOnlyHtml).toContain("Publish private");
    expect(privateOnlyHtml).toContain("Archive");
    expect(privateOnlyHtml).not.toContain("Publish public");
  });

  it("renders archived field rows as compact read-only rows", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="archived"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "headline",
              label: "Headline",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: null,
              archived: [
                {
                  id: "headline-archived",
                  value: "Old headline",
                  source: "user",
                  lifecycleStatus: "archived",
                  visibility: null,
                  archiveReason: "replaced"
                }
              ]
            }
          ],
          targets: []
        }}
      />
    );

    expect(html).toContain("Archived: replaced");
    expect(html).toContain("Old headline");
    expect(html).toContain("archived-field-value");
    expect(html).not.toContain("<input");
    expect(html).not.toContain("<textarea");
  });

  it("renders only real archived field values and supports multiple old values for one field", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="archived"
        activeTab="basics"
        draft={null}
        onProfileFieldUpdate={() => undefined}
        onTabChange={() => undefined}
        profileFields={{
          profileBasics: [
            {
              group: "profile_basics",
              name: "headline",
              label: "Headline",
              publicAllowed: true,
              privateOnly: false,
              multiline: false,
              generated: null,
              published: null,
              archived: [
                {
                  id: "headline-archived-empty",
                  value: "",
                  source: "user",
                  lifecycleStatus: "archived",
                  visibility: null,
                  archiveReason: "dismissed"
                },
                {
                  id: "headline-archived-old",
                  value: "Old headline",
                  source: "user",
                  lifecycleStatus: "archived",
                  visibility: null,
                  archiveReason: "replaced"
                },
                {
                  id: "headline-archived-older",
                  value: "Older headline",
                  source: "user",
                  lifecycleStatus: "archived",
                  visibility: null,
                  archiveReason: "replaced"
                }
              ]
            }
          ],
          targets: []
        }}
      />
    );

    expect(html).toContain("Old headline");
    expect(html).toContain("Older headline");
    expect(html).not.toContain("Blank value");
    expect(html.match(/Archived: replaced/g)?.length).toBe(2);
  });

  it("uses compact field row styling and removes stale Basics/Targets placeholders", () => {
    const source = readFileSync(new URL("./profile-workspace.tsx", import.meta.url), "utf8");
    const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

    expect(source).toContain("CompactEditableField");
    expect(source).toContain("field-lifecycle-title");
    expect(source).not.toContain("Private contact field schema pending");
    expect(source).not.toContain("Private cover-letter support field pending");
    expect(source).not.toContain("function TargetsCard");
    expect(source).not.toContain("function ProfileBasicsPanel");
    expect(css).toContain(".compact-field-editor");
    expect(css).toContain(".field-lifecycle-title");
  });

  it("renders generated items as autosaving form fields", () => {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, {
      assistantMessage: "I drafted updates and kept them private.",
      targetRoleIntent: {},
      draftFacts: [],
      skillClaims: [
        {
          skill: "LLM evals",
          category: "ai_systems",
          evidence: "Built eval workflows.",
          source: "chat",
          status: "needs_review",
          visibility: "private",
          published: false
        }
      ],
      experienceAndProjects: [],
      evidenceLinks: [],
      clarifyingQuestions: [],
      changeSummary: []
    });

    const html = renderToStaticMarkup(
      <ReviewTabbedList activeLifecycle="generated" activeTab="skills" draft={nextState.draft} onTabChange={() => undefined} />
    );

    expect(html).toContain("Skill");
    expect(html).toContain("Category");
    expect(html).toContain("Evidence");
    expect(html).toContain("Years min");
    expect(html).not.toContain("Save fact");
  });

  it("wires autosave to blur, Enter, and Cmd/Ctrl+Enter without keystroke saves", () => {
    const source = readFileSync(new URL("./profile-workspace.tsx", import.meta.url), "utf8");

    expect(source).toContain("onBlur: () => void saveIfChanged()");
    expect(source).toContain('event.key === "Enter"');
    expect(source).toContain("event.metaKey || event.ctrlKey");
    expect(source).not.toContain("onChange={(event) => onDraftItemUpdate");
  });

  it("shows internal-only published items in the Private tab without public items", () => {
    const html = renderToStaticMarkup(
      <ReviewTabbedList
        activeLifecycle="private"
        activeTab="facts"
        draft={null}
        onTabChange={() => undefined}
        publishedProfile={{
          facts: [
            {
              id: "internal-fact",
              claim: "Internal active fact.",
              category: "internal",
              source: "resume",
              visibility: "private",
              verificationStatus: "published"
            },
            {
              id: "public-fact",
              claim: "Public active fact.",
              category: "public",
              source: "resume",
              visibility: "public",
              verificationStatus: "published"
            }
          ]
        }}
      />
    );

    expect(html).toContain("Private");
    expect(html).toContain("Make public");
    expect(html).toContain("Internal active fact.");
    expect(html).not.toContain("Make private");
    expect(html).not.toContain("Public active fact.");
  });

  it("renders public published items with admin preview controls only in JobOps", () => {
    const html = renderToStaticMarkup(
      <PublicPortfolioPreview
        onEdit={() => undefined}
        onPublishedItemUpdate={() => undefined}
        publicPortfolioPath="/portfolio/chance-alpha"
        publishedPublicItemCount={1}
        publicProfile={{
          displayName: "Chance Alpha",
          headline: "Applied AI Engineer",
          summary: "Public summary.",
          profileStatus: "published",
          facts: [
            {
              id: "public-fact",
              claim: "Public active fact.",
              category: "impact",
              source: "resume",
              visibility: "public",
              verificationStatus: "published"
            },
            {
              id: "draft-fact",
              claim: "Draft public fact.",
              category: "draft",
              source: "resume",
              visibility: "public",
              verificationStatus: "draft"
            },
            {
              id: "private-fact",
              claim: "Private fact.",
              category: "private",
              source: "resume",
              visibility: "private",
              verificationStatus: "published"
            }
          ]
        }}
      />
    );

    expect(html).toContain("Public active fact.");
    expect(html).toContain("Make private");
    expect(html).toContain("Edit");
    expect(html).toContain("Archive");
    expect(html).not.toContain("Draft public fact.");
    expect(html).not.toContain("Private fact.");
  });

  it("renders field-level public basics and target controls in the JobOps preview", () => {
    const updates: Array<{ group: string; field: string; patch: unknown }> = [];
    const html = renderToStaticMarkup(
      <PublicPortfolioPreview
        onEdit={() => undefined}
        onProfileFieldUpdate={(group, field, patch) => {
          updates.push({ group, field, patch });
        }}
        onPublishedItemUpdate={() => undefined}
        publicPortfolioPath="/portfolio/chance-alpha"
        publishedPublicItemCount={4}
        publicProfile={{
          displayName: "Chance Alpha",
          headline: "Applied AI Engineer",
          summary: "Public summary.",
          profileStatus: "published",
          profileFields: {
            profileBasics: {
              displayName: "Chance Alpha",
              headline: "Applied AI Engineer",
              summary: "Public summary."
            },
            targets: {
              roleFamilies: "Applied AI; Forward deployed engineering",
              preferredWorkMode: "Remote",
              domainsOrIndustries: "Public-interest analytics"
            }
          },
          targetRoleIntent: {
            roleFamilies: ["Applied AI", "Forward deployed engineering"],
            workModes: ["Remote"],
            domainsOrIndustries: "Public-interest analytics",
            visibility: "public",
            publicationStatus: "published"
          }
        }}
      />
    );

    expect(updates).toHaveLength(0);
    expect(html).toContain("Name");
    expect(html).toContain("Headline");
    expect(html).toContain("Summary");
    expect(html).toContain("Target role families");
    expect(html).toContain("Preferred work mode");
    expect(html).toContain("Public-interest analytics");
    expect(html).toContain("Make private");
    expect(html).toContain("Archive");
  });

  it("does not render admin controls on the public portfolio component", () => {
    const html = renderToStaticMarkup(
      <PublicPortfolio
        source="api"
        profile={{
          id: "profile-1",
          slug: "chance-alpha",
          displayName: "Chance Alpha",
          headline: "Applied AI Engineer",
          summary: "Public summary.",
          profileStatus: "published",
          updatedAt: "2026-05-23T00:00:00.000Z",
          hasPublishedPublicContent: true,
          targetRoleIntent: {
            targetTitles: ["Applied AI Engineer"],
            roleFamilies: ["Applied AI"],
            workModes: ["Remote"],
            preferredLocations: ["Louisville"],
            domainsOrIndustries: "Public-interest analytics",
            constraints: "Mission-driven teams"
          },
          facts: [
            {
              id: "public-fact",
              claim: "Public active fact.",
              category: "impact",
              source: "resume",
              visibility: "public",
              verificationStatus: "published"
            }
          ]
        }}
      />
    );

    expect(html).toContain("Public active fact.");
    expect(html).toContain("Role families");
    expect(html).toContain("Applied AI");
    expect(html).toContain("Work mode");
    expect(html).toContain("Remote");
    expect(html).toContain("Domains or industries");
    expect(html).toContain("Public-interest analytics");
    expect(html).not.toContain("Make private");
    expect(html).not.toContain("Archive");
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
    expect(html).toContain("Organization");
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

  it("loads saved profile review state from the profile proxy", async () => {
    const { readFile } = await import("node:fs/promises");
    const source = await readFile(new URL("./profile-workspace.tsx", import.meta.url), "utf-8");

    expect(source).toContain('apiBasePath = "/api"');
    expect(source).toContain('fetch(`${apiBasePath}/profile`)');
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
