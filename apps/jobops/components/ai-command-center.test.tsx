import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AiCommandCenter, MarkdownMessage, buildCommandCenterClientContext, starterPrompts, type CommandMessage } from "./ai-command-center";
import {
  classifyCommand,
  createPlannedAction,
  summarizeCommandForDisplay,
  workspaceRoutes,
  type PlannedCommandAction,
  type WorkspaceTab
} from "../lib/command-center-actions";

describe("AI command center", () => {
  it("renders prominently with starter prompts", () => {
    const html = renderToStaticMarkup(<AiCommandCenter />);

    expect(html).toContain("AI command center");
    expect(html).toContain("Ask JobOps to work across your search.");
    expect(html).not.toContain("JobOps agent");
    expect(html).toContain("Examples");
    expect(html).toContain("Show examples");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-controls="jobops-starter-prompts"');
    expect(html).toContain('id="jobops-starter-prompts"');
    expect(html).toContain("I want to be an Applied AI Engineer.");
    for (const prompt of starterPrompts.slice(1)) {
      expect(html).toContain(prompt.replace("'", "&#x27;"));
    }
  });

  it("keeps starter prompts wired to the command composer", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain("const [areExamplesExpanded, setAreExamplesExpanded] = useState(false)");
    expect(source).toContain('aria-expanded={areExamplesExpanded}');
    expect(source).toContain("setAreExamplesExpanded((current) => !current)");
    expect(source).toContain("starterPrompts.map((prompt)");
    expect(source).toContain("onClick={() => setCommand(prompt)}");
  });

  it("renders the command composer controls", () => {
    const html = renderToStaticMarkup(<AiCommandCenter />);

    expect(html).toContain('for="jobops-command"');
    expect(html).toContain(">Command</label>");
    expect(html).toContain('id="jobops-command"');
    expect(html).toContain("<textarea");
    expect(html).toContain("Add file");
    expect(html).toContain("Run command");
  });

  it("creates a planned action card from a submitted command plan", () => {
    const plannedAction = createPlannedAction("Here's a job URL. Add it to my jobs list.", "action-test");
    const html = renderToStaticMarkup(<AiCommandCenter initialActions={[plannedAction]} />);

    expect(plannedAction).toMatchObject({
      type: "add_job_from_url",
      status: "planned",
      targetWorkspace: "jobs"
    });
    expect(html).toContain("Add job from URL");
    expect(html).toContain("add_job_from_url");
    expect(html).toContain("Jobs");
  });

  it("truncates long fallback action summaries and classifies resume-shaped text as profile intake", () => {
    const longResume = [
      "PROFESSIONAL SUMMARY",
      "Applied AI Systems Engineer building production RAG systems.",
      "CORE SKILLS",
      "Python, FastAPI, PostgreSQL, LLM evaluation.",
      "PROFESSIONAL EXPERIENCE",
      "Shadow Network Intelligence - Founder - 2024-Present",
      "Built AI reporting workflows."
    ].join("\n").repeat(30);
    const plannedAction = createPlannedAction(longResume, "action-long-resume");

    expect(classifyCommand(longResume).type).toBe("profile_intake");
    expect(plannedAction.type).toBe("profile_intake");
    expect(plannedAction.summary).toContain("...");
    expect(plannedAction.summary).toContain("chars");
    expect(plannedAction.summary.length).toBeLessThan(320);
    expect(plannedAction.summary).not.toContain("Built AI reporting workflows.PROFESSIONAL SUMMARY");
    expect(summarizeCommandForDisplay(longResume).length).toBeLessThan(220);
  });

  it("truncates action-card summaries defensively at render time", () => {
    const noisyTail = "DO_NOT_RENDER_FULL_RESUME_TAIL";
    const html = renderToStaticMarkup(
      <AiCommandCenter
        initialActions={[
          {
            id: "action-long-summary",
            type: "unknown",
            title: "Review command",
            summary: `${"Long pasted resume text ".repeat(40)}${noisyTail}`,
            status: "planned"
          }
        ]}
      />
    );

    expect(html).toContain("Long pasted resume text");
    expect(html).not.toContain(noisyTail);
  });

  it("renders a completed profile-intake action card", () => {
    const html = renderToStaticMarkup(
      <AiCommandCenter
        initialActions={[
          {
            id: "action-profile",
            type: "profile_intake",
            title: "Update profile",
            summary: "Updated the saved profile draft.",
            status: "completed",
            targetWorkspace: "profile"
          }
        ]}
      />
    );

    expect(html).toContain("Update profile");
    expect(html).toContain("profile_intake");
    expect(html).toContain("completed");
    expect(html).toContain("href=\"/profile\"");
  });

  it("renders assistant markdown with safe links, lists, emphasis, and code", () => {
    const html = renderToStaticMarkup(
      <MarkdownMessage
        text={[
          "Here is **guidance** with *emphasis* and `inline code`.",
          "",
          "- First item",
          "- [Safe link](https://example.com)",
          "- [Unsafe link](javascript:alert(1))",
          "",
          "```ts",
          "const ok = true;",
          "```"
        ].join("\n")}
      />
    );

    expect(html).toContain("<strong>guidance</strong>");
    expect(html).toContain("<em>emphasis</em>");
    expect(html).toContain("<code>inline code</code>");
    expect(html).toContain("<ul>");
    expect(html).toContain('href="https://example.com"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain("const ok = true;");
    expect(html).not.toContain("href=\"javascript:alert(1)\"");
  });

  it("prints model request and response debug payloads on profile-intake action cards", () => {
    const html = renderToStaticMarkup(
      <AiCommandCenter
        initialActions={[
          {
            id: "action-profile-debug",
            type: "profile_intake",
            title: "Update profile",
            summary: "Updated the saved profile draft.",
            status: "completed",
            targetWorkspace: "profile",
            resultPayload: {
              modelRequest: {
                task: "profile_draft_update",
                messages: [
                  { role: "system", content: "System prompt" },
                  { role: "user", content: "Louisville, KY is in the current draft" }
                ]
              },
              modelResponse: {
                finishReason: "STOP",
                text: "{\"assistantMessage\":\"Drafted.\"}"
              }
            }
          }
        ]}
      />
    );

    expect(html).toContain("Sent to model");
    expect(html).toContain("profile_draft_update");
    expect(html).toContain("Louisville, KY is in the current draft");
    expect(html).toContain("Model response");
    expect(html).toContain("Drafted.");
  });

  it("renders job discovery diagnostics on action cards", () => {
    const html = renderToStaticMarkup(
      <AiCommandCenter
        initialActions={[
          {
            id: "action-job-debug",
            type: "job_discovery",
            title: "Discover jobs",
            summary: "No new jobs were saved.",
            status: "completed",
            targetWorkspace: "jobs",
            resultPayload: {
              jobDiscoveryMode: "live_provider",
              sourceName: "test_provider",
              providerResultCount: 8,
              verifiedUrlCount: 6,
              savedJobCount: 2,
              duplicateCount: 4,
              skippedReasons: {
                duplicate_for_user: 4,
                failed_url_verification: 2
              }
            }
          }
        ]}
      />
    );

    expect(html).toContain("Job discovery diagnostics");
    expect(html).toContain("live_provider");
    expect(html).toContain("test_provider");
    expect(html).toContain("Provider results");
    expect(html).toContain("Verified URLs");
    expect(html).toContain("duplicate_for_user: 4");
  });

  it("notifies the profile workspace after completed profile-intake commands", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain('action.type === "profile_intake"');
    expect(source).toContain('window.dispatchEvent(new CustomEvent("jobops:profile-draft-updated"');
  });

  it("notifies the jobs workspace after completed job-discovery commands", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain('action.type === "job_discovery"');
    expect(source).toContain('window.dispatchEvent(new CustomEvent("jobops:jobs-updated"');
    expect(source).toContain('window.dispatchEvent(new CustomEvent("jobops:companies-updated"');
  });

  it("polls async job-discovery runs without replaying commands", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain('const JOB_DISCOVERY_RUN_STORAGE_KEY = "jobops.activeJobDiscoveryRunId"');
    expect(source).toContain("setActiveJobDiscoveryRunId(runId)");
    expect(source).toContain("storeJobDiscoveryRunId(runId)");
    expect(source).toContain('fetch(`${apiBasePath}/job-search-runs/${encodeURIComponent(runId)}`');
    expect(source).toContain("TERMINAL_JOB_SEARCH_RUN_STATUSES.has(run.status)");
    expect(source).toContain('window.dispatchEvent(new CustomEvent("jobops:jobs-updated"');
    expect(source).toContain("without replaying the command");
    expect(source).toContain("clearStoredJobDiscoveryRunId(run.id)");
  });

  it("returns from the stream as soon as an async result event is parsed", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain("result = event.result;");
    expect(source).toContain("return result;");
    expect(source).not.toContain("reader.cancel()");
  });

  it("adds router status updates to the transcript", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain("Status update: sending this command to the JobOps router.");
    expect(source).toContain("buildCommandCenterClientContext(messages, submittedCommand)");
    expect(source).toContain('const requestUrl = `${apiBasePath}/command-center/stream`;');
    expect(source).toContain("fetch(requestUrl");
    expect(source).toContain("Command-center stream returned a non-NDJSON response.");
    expect(source).toContain("Command-center fallback returned a non-JSON response.");
    expect(source).toContain("bodyPreview: previewDiagnosticBody(body)");
    expect(source).toContain("responseUrl: response.url || null");
    expect(source).toContain("onStatus(event.statusUpdate)");
    expect(source).toContain("latestRoutedStreamStatus(streamStatusUpdates)");
    expect(source).toContain("createInterruptedFallbackAction(submittedCommand");
    expect(source).toContain("shouldAvoidFallbackReplay(interruptedAction)");
    expect(source).toContain("the command stream was interrupted before the final result reached the browser");
    expect(source).toContain("I did not re-run it to avoid duplicate changes.");
    expect(source).toContain("The command was not replayed to avoid duplicate changes.");
    expect(source).toContain("no router decision was received");
    expect(source).toContain("formatTranscriptMessage(submittedCommand)");
    expect(source).toContain("messages.map((message)");
    expect(source).toContain('message.role === "user" ? <strong>You</strong> : null');
    expect(source).toContain("<MarkdownMessage text={message.text} />");
    expect(source).toContain("if (isStructuredCommandCenterError(error))");
    expect(source).toContain("isStructuredCommandCenterError(fallbackError)");
    expect(source).not.toContain("JobOps agent");
    expect(source).not.toContain("messages.slice(-4)");
  });

  it("builds command-center client context with the active transcript and raw submitted text", () => {
    const messages: CommandMessage[] = [
      {
        id: "agent-0",
        role: "agent",
        text: "Tell JobOps what you want."
      },
      {
        id: "user-1",
        role: "user",
        text: "Pasted message: \"short preview...\"",
        rawText: "Full pasted resume text with RAG and LLM evaluation."
      },
      {
        id: "agent-status-1",
        role: "agent",
        text: "Status update: previous guidance completed."
      }
    ];

    const context = buildCommandCenterClientContext(messages, "So what should I do?");

    expect(context.transcript.source).toBe("jobops_command_center_active_thread");
    expect(context.transcript.messages).toEqual([
      { role: "assistant", type: "message", text: "Tell JobOps what you want." },
      { role: "user", type: "message", text: "Full pasted resume text with RAG and LLM evaluation." },
      { role: "assistant", type: "status", text: "Status update: previous guidance completed." },
      { role: "user", type: "message", text: "So what should I do?" }
    ]);
  });

  it("submits textarea messages on Enter while preserving Shift+Enter for multiline input", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain("handleCommandKeyDown");
    expect(source).toContain('event.key !== "Enter"');
    expect(source).toContain("event.shiftKey");
    expect(source).toContain("event.nativeEvent.isComposing");
    expect(source).toContain("event.currentTarget.form?.requestSubmit()");
    expect(source).toContain("onKeyDown={handleCommandKeyDown}");
  });

  it("links planned action CTAs to the expected workspace routes", () => {
    const workspaces = Object.keys(workspaceRoutes) as WorkspaceTab[];

    for (const workspace of workspaces) {
      const route = workspaceRoutes[workspace];
      const action: PlannedCommandAction = {
        id: `action-${workspace}`,
        type: "unknown",
        title: `Open ${workspace}`,
        summary: `Planned action for ${workspace}.`,
        status: "planned",
        targetWorkspace: workspace,
        ctaLabel: `Open ${workspace}`
      };
      const html = renderToStaticMarkup(<AiCommandCenter initialActions={[action]} />);

      expect(html).toContain(`href="${route}"`);
      expect(html).toContain(`Open ${workspace}`);
    }
  });

  it("shows a non-action affordance when no target workspace exists", () => {
    const html = renderToStaticMarkup(
      <AiCommandCenter
        initialActions={[
          {
            id: "action-unknown",
            type: "unknown",
            title: "Review command",
            summary: "JobOps needs more information before routing.",
            status: "planned"
          }
        ]}
      />
    );

    expect(html).toContain("Planned");
    expect(html).not.toContain("href=");
  });

  it("classifies common command examples into planned action types", () => {
    expect(classifyCommand("Here's a job URL. Add it to my jobs list.").type).toBe("add_job_from_url");
    expect(classifyCommand("Find me some jobs to apply to.").type).toBe("job_discovery");
    expect(classifyCommand("Find some jobs for me to apply to.").type).toBe("job_discovery");
    expect(classifyCommand("find some jobs from my companies list").type).toBe("job_discovery");
    expect(classifyCommand("Find applied AI engineer jobs.").type).toBe("job_discovery");
    expect(classifyCommand("Show me roles I should consider.").type).toBe("job_discovery");
    expect(classifyCommand("Follow this company.").type).toBe("company_discovery");
    expect(classifyCommand("Find civic tech companies to follow.").type).toBe("company_discovery");
    expect(classifyCommand("Are there any companies that I should be following, who hire for roles like this?").type).toBe("company_discovery");
    expect(classifyCommand("Update CivicActions job listings URL to https://example.com/jobs").type).toBe("company_update");
    expect(classifyCommand("Which jobs should I apply to today?").type).toBe("prioritize_jobs");
    expect(classifyCommand("Prioritize my saved jobs.").type).toBe("prioritize_jobs");
    expect(classifyCommand("Generate application materials for this role.").type).toBe("generate_materials");
    expect(classifyCommand("Mark this job as applied.").type).toBe("mark_applied");
    expect(classifyCommand("I want to be an Applied AI Engineer.").type).toBe("profile_intake");
    expect(classifyCommand("Update my profile with this project.").type).toBe("profile_intake");
    expect(classifyCommand("What should I follow up on this week?").type).toBe("follow_up_review");
    expect(classifyCommand("Make something happen.").type).toBe("unknown");
  });

  it("submits commands only to the thin Next.js command-center proxy", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain('apiBasePath = "/api"');
    expect(source).toContain('const requestUrl = `${apiBasePath}/command-center/stream`;');
    expect(source).toContain("fetch(requestUrl");
    expect(source).not.toContain("/v1/command");
    expect(source).not.toContain("GEMINI_API_KEY");
    expect(source).not.toContain("@jobops/model-connector");
    expect(source).not.toContain("generateContent");
  });

  it("mounts the portfolio-hosted command-center stream wrapper on the standalone JobOps route", async () => {
    const wrapperSource = await readFile(
      new URL("../../portfolio/app/jobops/api/command-center/stream/route.ts", import.meta.url),
      "utf-8"
    );
    const standaloneSource = await readFile(new URL("../app/api/command-center/stream/route.ts", import.meta.url), "utf-8");

    expect(wrapperSource).toContain(
      'export { POST } from "../../../../../../jobops/app/api/command-center/stream/route"'
    );
    expect(wrapperSource).toContain('export const runtime = "nodejs"');
    expect(standaloneSource).toContain("/v1/command-center/commands/stream");
    expect(standaloneSource).toContain("Command-center stream proxy request.");
    expect(standaloneSource).toContain("commandLength");
    expect(standaloneSource).not.toContain("latestUserMessage");
    expect(standaloneSource).not.toContain("userMessage");
  });

  it("keeps model calls out of Next.js command-center code", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");
    const routeSource = await readFile(new URL("../app/api/command-center/route.ts", import.meta.url), "utf-8");
    const combinedSource = `${source}\n${routeSource}`;

    expect(combinedSource).not.toContain("@jobops/model-connector");
    expect(combinedSource).not.toContain("runProfileIntakeExtraction");
    expect(combinedSource).not.toContain("buildProfileIntakeUserPrompt");
    expect(combinedSource).not.toContain("generateContent");
  });

  it("caps the command center to the viewport and scrolls chat content internally", async () => {
    const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf-8");

    expect(css).toContain("max-height: calc(100svh - 112px)");
    expect(css).toContain("grid-template-rows: auto minmax(0, 1fr) auto auto");
    expect(css).toContain("overflow-y: auto");
    expect(css).toContain("overflow-wrap: anywhere");
    expect(css).toContain(".command-message.user");
    expect(css).toContain("border: 1px solid rgba(15, 118, 110, 0.28)");
    expect(css).toContain("color: var(--ink)");
    expect(css).toContain("command-scroll-latest");
    expect(css).toContain("position: absolute");
    expect(css).toContain(".command-message.agent:not(.status)");
    expect(css).toContain(".command-message.status");
    expect(css).toContain(".command-message-markdown");

    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");
    expect(source).toContain("conversation.scrollTop = conversation.scrollHeight");
    expect(source).toContain("shouldStickToBottomRef.current");
    expect(source).toContain("setHasNewMessagesBelow(true)");
    expect(source).toContain("onScroll={handleConversationScroll}");
  });

  it("includes mobile command-center layout rules for chat, examples, composer, and actions", async () => {
    const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf-8");

    expect(css).toContain("@media (max-width: 720px)");
    expect(css).toContain(".ai-command-center");
    expect(css).toContain("max-height: none");
    expect(css).toContain("overflow: visible");
    expect(css).toContain(".command-center-grid");
    expect(css).toContain("display: contents");
    expect(css).toContain(".command-conversation-frame");
    expect(css).toContain("min-height: 220px");
    expect(css).toContain("max-height: 42svh");
    expect(css).toContain(".starter-prompts-panel.expanded .starter-prompts");
    expect(css).toContain("overflow-x: auto");
    expect(css).toContain(".command-composer");
    expect(css).toContain("order: 4");
    expect(css).toContain(".agent-action-rail");
    expect(css).toContain("max-height: 220px");
  });
});
