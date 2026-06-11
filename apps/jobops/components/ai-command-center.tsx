"use client";

import Link from "next/link";
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  createPlannedAction,
  formatWorkspaceLabel,
  getWorkspaceRoute,
  summarizeCommandForDisplay,
  type PlannedCommandAction,
  type WorkspaceTab
} from "../lib/command-center-actions";
import type {
  CommandCenterApiResponse,
  CommandCenterProxyResponse,
  CommandCenterStatusUpdate,
  CommandCenterStreamEvent,
  JobSearchRunStatus
} from "../lib/command-center-contract";

export type CommandMessage = {
  id: string;
  role: "agent" | "user";
  text: string;
  rawText?: string;
};

const starterPrompts = [
  "I want to be an Applied AI Engineer.",
  "Update my profile with this project.",
  "Find companies in progressive politics hiring AI engineers.",
  "Find me some jobs to apply to.",
  "Here's a job URL. Add it to my jobs list.",
  "Follow this company.",
  "Which jobs should I apply to today?",
  "Generate materials for this application."
];

const TRANSCRIPT_PREVIEW_MAX_CHARS = 520;
const ACTION_SUMMARY_MAX_CHARS = 360;
const SCROLL_BOTTOM_THRESHOLD_PX = 48;
const COMMAND_CENTER_DIAGNOSTIC_BODY_PREVIEW_CHARS = 200;
const SAFE_LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);
const JOB_DISCOVERY_RUN_STORAGE_KEY = "jobops.activeJobDiscoveryRunId";
const JOB_DISCOVERY_POLL_INTERVAL_MS = 2500;
const TERMINAL_JOB_SEARCH_RUN_STATUSES = new Set(["completed", "failed", "needs_confirmation", "cancelled"]);

const initialMessages: CommandMessage[] = [
  {
    id: "agent-0",
    role: "agent",
    text: "Tell JobOps what you want to move forward. I can update your profile draft now and route future tools to the right workspace."
  }
];

export function AiCommandCenter({
  activeWorkspace,
  apiBasePath = "/api",
  initialActions = [],
  workspaceBasePath = ""
}: {
  activeWorkspace?: WorkspaceTab;
  apiBasePath?: string;
  initialActions?: PlannedCommandAction[];
  workspaceBasePath?: string;
}) {
  const [command, setCommand] = useState("");
  const [messages, setMessages] = useState<CommandMessage[]>(initialMessages);
  const [actions, setActions] = useState<PlannedCommandAction[]>(initialActions);
  const [attachmentStatus, setAttachmentStatus] = useState("");
  const [areExamplesExpanded, setAreExamplesExpanded] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeJobDiscoveryRunId, setActiveJobDiscoveryRunId] = useState<string | null>(null);
  const [hasNewMessagesBelow, setHasNewMessagesBelow] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const reportedJobDiscoveryRunIdsRef = useRef(new Set<string>());
  const pollingFailureRunIdsRef = useRef(new Set<string>());

  const latestAction = actions[0];
  const transcriptLabel = useMemo(
    () => (latestAction ? `Latest planned action: ${latestAction.title}` : "Command history"),
    [latestAction]
  );

  useEffect(() => {
    const conversation = conversationRef.current;
    if (!conversation) {
      return;
    }

    if (!shouldStickToBottomRef.current) {
      setHasNewMessagesBelow(true);
      return;
    }

    window.requestAnimationFrame(() => {
      scrollConversationToBottom();
    });
  }, [messages]);

  useEffect(() => {
    const storedRunId = readStoredJobDiscoveryRunId();
    if (storedRunId) {
      setActiveJobDiscoveryRunId(storedRunId);
    }
  }, []);

  useEffect(() => {
    if (!activeJobDiscoveryRunId) {
      return;
    }

    const runId = activeJobDiscoveryRunId;
    let cancelled = false;
    let timeoutId: number | null = null;

    async function pollRunStatus() {
      try {
        const run = await fetchJobSearchRunStatus(runId, apiBasePath);
        if (cancelled) {
          return;
        }
        pollingFailureRunIdsRef.current.delete(run.id);
        updateJobDiscoveryActionFromRun(run);
        if (TERMINAL_JOB_SEARCH_RUN_STATUSES.has(run.status)) {
          clearStoredJobDiscoveryRunId(run.id);
          setActiveJobDiscoveryRunId((current) => (current === run.id ? null : current));
          addTerminalJobDiscoveryRunMessage(run);
          return;
        }
      } catch {
        if (!cancelled && !pollingFailureRunIdsRef.current.has(runId)) {
          pollingFailureRunIdsRef.current.add(runId);
          setMessages((current) => [
            ...current,
            {
              id: `agent-job-run-polling-${Date.now()}-${current.length}`,
              role: "agent",
              text: "Status update: job discovery is still running, but this browser could not read the latest run status yet. I will keep polling without replaying the command."
            }
          ]);
        }
      }

      if (!cancelled) {
        timeoutId = window.setTimeout(pollRunStatus, JOB_DISCOVERY_POLL_INTERVAL_MS);
      }
    }

    pollRunStatus();
    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [activeJobDiscoveryRunId, apiBasePath]);

  function handleConversationScroll() {
    const conversation = conversationRef.current;
    if (!conversation) {
      return;
    }

    const isAtBottom = isScrolledNearBottom(conversation);
    shouldStickToBottomRef.current = isAtBottom;
    if (isAtBottom) {
      setHasNewMessagesBelow(false);
    }
  }

  function scrollConversationToBottom() {
    const conversation = conversationRef.current;
    if (!conversation) {
      return;
    }

    conversation.scrollTop = conversation.scrollHeight;
    shouldStickToBottomRef.current = true;
    setHasNewMessagesBelow(false);
  }

  function handleCommandKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }

    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }

    const submittedCommand = command.trim();
    if (!submittedCommand) {
      return;
    }
    const plannedPreview = createPlannedAction(submittedCommand, "preview");
    if (activeJobDiscoveryRunId && plannedPreview.type === "job_discovery") {
      setMessages((current) => [
        ...current,
        {
          id: `agent-active-job-run-${Date.now()}-${current.length}`,
          role: "agent",
          text: "Status update: a job discovery run is already in progress. Wait for it to finish before starting another discovery run."
        }
      ]);
      return;
    }

    const submissionId = Date.now();
    const clientContext = buildCommandCenterClientContext(messages, submittedCommand);
    setMessages((current) => [
      ...current,
      {
        id: `user-${submissionId}`,
        role: "user",
        text: formatTranscriptMessage(submittedCommand),
        rawText: submittedCommand
      },
      {
        id: `agent-status-submitted-${submissionId}`,
        role: "agent",
        text: "Status update: sending this command to the JobOps router."
      }
    ]);
    setCommand("");
    setIsSubmitting(true);
    const streamStatusUpdates: CommandCenterStatusUpdate[] = [];

    try {
      const result = await runCommandCenterStream({
        activeWorkspace,
        apiBasePath,
        clientContext,
        command: submittedCommand,
        onStatus: (statusUpdate) => {
          streamStatusUpdates.push(statusUpdate);
          setMessages((current) => [
            ...current,
            {
              id: `agent-status-${Date.now()}-${current.length}`,
              role: "agent",
              text: statusUpdate.message
            }
          ]);
        }
      });

      applyCommandCenterResult(result);
    } catch (error) {
      if (isStructuredCommandCenterError(error)) {
        const message = error.message || "Command-center API returned a structured error.";
        setMessages((current) => [
          ...current,
          {
            id: `agent-error-${Date.now()}-${current.length}`,
            role: "agent",
            text: `Status update: ${message}`
          }
        ]);
        setIsSubmitting(false);
        return;
      }

      const interruptedStatus = latestRoutedStreamStatus(streamStatusUpdates);
      const interruptedAction = interruptedStatus
        ? createInterruptedStreamAction(submittedCommand, interruptedStatus, `action-${Date.now()}`)
        : createInterruptedFallbackAction(submittedCommand, `action-${Date.now()}`);
      if (interruptedStatus || shouldAvoidFallbackReplay(interruptedAction)) {
        addInterruptedStreamMessage(interruptedAction, Boolean(interruptedStatus));
        setIsSubmitting(false);
        return;
      }

      try {
        const fallbackRequestUrl = `${apiBasePath}/command-center`;
        const response = await fetch(fallbackRequestUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            command: submittedCommand,
            activeWorkspace,
            clientContext
          })
        });
        const payload = await readCommandCenterProxyResponse(response, fallbackRequestUrl);

        if (!response.ok || !payload.ok) {
          throw new Error(payload.ok ? "Command-center request failed." : payload.error);
        }

        applyCommandCenterResult(payload.result);
      } catch (fallbackError) {
        const message = fallbackError instanceof Error ? fallbackError.message : "Command-center API is unavailable.";
        if (isStructuredCommandCenterError(fallbackError)) {
          setMessages((current) => [
            ...current,
            {
              id: `agent-error-${Date.now()}-${current.length}`,
              role: "agent",
              text: `Status update: ${message}`
            }
          ]);
          return;
        }

        const fallbackAction = createPlannedAction(submittedCommand, `action-${Date.now()}`);
        const workspace = fallbackAction.targetWorkspace ? formatWorkspaceLabel(fallbackAction.targetWorkspace) : "Command Center";

        setActions((current) => [fallbackAction, ...current]);
        setMessages((current) => [
          ...current,
          {
            id: `agent-${current.length + 1}`,
            role: "agent",
            text: `${message} Status update: no router decision was received, so this card is only a local fallback for ${workspace}.`
          }
        ]);
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  function applyCommandCenterResult(result: CommandCenterApiResponse) {
    const nextActions = result.actions.map((action, index) => ({
      ...action,
      id: action.id ?? `action-${Date.now()}-${index}`,
      ctaLabel:
        action.ctaLabel ??
        (action.targetWorkspace ? `Open ${formatWorkspaceLabel(action.targetWorkspace)}` : undefined)
    }));

    setActions((current) => [...nextActions, ...current]);
    setMessages((current) => [
      ...current,
      {
        id: `agent-${current.length + 1}`,
        role: "agent",
        text: result.assistant_message
      }
    ]);

    if (nextActions.some((action) => action.type === "profile_intake" && action.status === "completed")) {
      window.dispatchEvent(new CustomEvent("jobops:profile-draft-updated"));
    }
    if (nextActions.some((action) => action.type === "company_discovery" && action.status === "completed")) {
      window.dispatchEvent(new CustomEvent("jobops:companies-updated"));
    }
    if (nextActions.some((action) => action.type === "job_discovery" && action.status === "completed")) {
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      window.dispatchEvent(new CustomEvent("jobops:companies-updated"));
    }
    const runId = nextActions.map(getAsyncJobDiscoveryRunId).find(Boolean);
    if (runId) {
      storeJobDiscoveryRunId(runId);
      setActiveJobDiscoveryRunId(runId);
    }
  }

  function updateJobDiscoveryActionFromRun(run: JobSearchRunStatus) {
    setActions((current) => {
      const nextStatus =
        run.status === "completed"
          ? "completed"
          : run.status === "failed" || run.status === "cancelled"
            ? "failed"
            : run.status === "needs_confirmation"
              ? "needs_confirmation"
              : "running";
      const nextSummary = run.status === "completed" ? buildJobDiscoveryRunSummary(run) : run.message || buildJobDiscoveryRunSummary(run);
      let matched = false;
      const updated = current.map((action) => {
        const payloadRunId = getAsyncJobDiscoveryRunId(action);
        if (action.type !== "job_discovery" || payloadRunId !== run.id) {
          return action;
        }
        matched = true;
        return {
          ...action,
          status: nextStatus,
          summary: nextSummary,
          resultPayload: {
            ...(isRecord(action.resultPayload) ? action.resultPayload : {}),
            async: true,
            jobSearchRunId: run.id,
            status: run.status,
            providerResultCount: run.providerResultCount,
            candidatePoolCount: run.candidatePoolCount,
            candidateCountAfterDedupe: run.candidateCountAfterDedupe,
            modelSelectedCount: run.modelSelectedCount,
            savedCount: run.savedCount,
            updatedExistingCount: run.updatedExistingCount,
            duplicateCount: run.duplicateCount,
            skippedCount: run.skippedCount,
            providerErrorCount: run.providerErrorCount,
            jobDiscoveryMode: run.jobDiscoveryMode ?? run.searchMode ?? undefined,
            diagnostics: run.diagnostics,
            diagnosticMessages: run.diagnosticMessages ?? undefined,
            modelReviewCompleted: run.modelReviewCompleted ?? undefined,
            modelReviewFailureReason: run.modelReviewFailureReason ?? undefined,
            noJobsAddedReason: run.noJobsAddedReason ?? undefined,
            addedJobs: run.addedJobs ?? [],
            addedJobIds: run.addedJobIds ?? [],
            jobs: run.addedJobs ?? [],
            highlightedJobSearchRunId: run.highlightedJobSearchRunId ?? undefined,
            userVisibleSummary: run.userVisibleSummary ?? undefined,
            userSummary: run.userSummary ?? undefined,
            plannerRationale: run.plannerRationale ?? undefined,
            plannerFallbackUsed: run.plannerFallbackUsed ?? undefined,
            recentSearchesUsed: run.recentSearchesUsed,
            selectionAssistantMessage: run.selectionAssistantMessage ?? undefined,
            selectionSkippedCandidateNotes: run.selectionSkippedCandidateNotes,
            selectionClarifyingQuestions: run.selectionClarifyingQuestions,
            replansAttempted: run.replansAttempted,
            replanLimit: run.replanLimit ?? undefined,
            replanningStatus: run.replanningStatus ?? undefined,
            replanningDecision: run.replanningDecision ?? undefined,
            replanReason: run.replanReason ?? undefined,
            replanReasons: run.replanReasons,
            replanQueries: run.replanQueries,
            error: run.error ?? undefined
          }
        } satisfies PlannedCommandAction;
      });
      if (matched) {
        return updated;
      }
      return [
        {
          id: `action-job-run-${run.id}`,
          type: "job_discovery",
          title: "Discover jobs",
          summary: nextSummary,
          status: nextStatus,
          targetWorkspace: "jobs",
          ctaLabel: "Open Jobs",
          resultPayload: {
            async: true,
            jobSearchRunId: run.id,
            status: run.status,
            savedCount: run.savedCount,
            updatedExistingCount: run.updatedExistingCount,
            duplicateCount: run.duplicateCount,
            skippedCount: run.skippedCount,
            providerResultCount: run.providerResultCount,
            candidatePoolCount: run.candidatePoolCount,
            candidateCountAfterDedupe: run.candidateCountAfterDedupe,
            modelSelectedCount: run.modelSelectedCount,
            providerErrorCount: run.providerErrorCount,
            jobDiscoveryMode: run.jobDiscoveryMode ?? run.searchMode ?? undefined,
            diagnostics: run.diagnostics,
            diagnosticMessages: run.diagnosticMessages ?? undefined,
            modelReviewCompleted: run.modelReviewCompleted ?? undefined,
            modelReviewFailureReason: run.modelReviewFailureReason ?? undefined,
            noJobsAddedReason: run.noJobsAddedReason ?? undefined,
            addedJobs: run.addedJobs ?? [],
            addedJobIds: run.addedJobIds ?? [],
            jobs: run.addedJobs ?? [],
            highlightedJobSearchRunId: run.highlightedJobSearchRunId ?? undefined,
            userVisibleSummary: run.userVisibleSummary ?? undefined,
            userSummary: run.userSummary ?? undefined,
            plannerRationale: run.plannerRationale ?? undefined,
            plannerFallbackUsed: run.plannerFallbackUsed ?? undefined,
            recentSearchesUsed: run.recentSearchesUsed,
            selectionAssistantMessage: run.selectionAssistantMessage ?? undefined,
            selectionSkippedCandidateNotes: run.selectionSkippedCandidateNotes,
            selectionClarifyingQuestions: run.selectionClarifyingQuestions,
            replansAttempted: run.replansAttempted,
            replanLimit: run.replanLimit ?? undefined,
            replanningStatus: run.replanningStatus ?? undefined,
            replanningDecision: run.replanningDecision ?? undefined,
            replanReason: run.replanReason ?? undefined,
            replanReasons: run.replanReasons,
            replanQueries: run.replanQueries
          }
        },
        ...updated
      ];
    });
  }

  function addTerminalJobDiscoveryRunMessage(run: JobSearchRunStatus) {
    if (reportedJobDiscoveryRunIdsRef.current.has(run.id)) {
      return;
    }
    reportedJobDiscoveryRunIdsRef.current.add(run.id);
    setMessages((current) => [
      ...current,
      {
        id: `agent-job-run-${Date.now()}-${current.length}`,
        role: "agent",
        text:
          run.status === "completed"
            ? buildJobDiscoveryRunSummary(run)
            : `Job discovery failed: ${run.error || run.message || "No jobs were saved."}`
      }
    ]);
    if (run.status === "completed") {
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      window.dispatchEvent(new CustomEvent("jobops:companies-updated"));
    }
  }

  function addInterruptedStreamMessage(interruptedAction: PlannedCommandAction, wasRouted: boolean) {
    const workspace = interruptedAction.targetWorkspace ? formatWorkspaceLabel(interruptedAction.targetWorkspace) : "Command Center";
    setActions((current) => [interruptedAction, ...current]);
    setMessages((current) => [
      ...current,
      {
        id: `agent-interrupted-${Date.now()}-${current.length}`,
        role: "agent",
        text: wasRouted
          ? `Status update: the command stream was interrupted after routing to ${interruptedAction.title}. I did not re-run it to avoid duplicate changes. Refresh or open ${workspace} to check the latest saved results.`
          : `Status update: the command stream was interrupted before the final result reached the browser. I did not re-run this ${interruptedAction.title} command to avoid duplicate changes. Refresh or open ${workspace} to check the latest saved results.`
      }
    ]);
  }

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!isTextUpload(file, extension)) {
      setAttachmentStatus(`${file.name} selected, but PDF/DOCX extraction is not wired yet. Export or paste text for now.`);
      return;
    }

    try {
      const text = await file.text();
      const trimmed = text.trim();
      if (!trimmed) {
        setAttachmentStatus(`${file.name} did not contain readable text.`);
        return;
      }
      setCommand((current) =>
        [
          current.trim(),
          `Resume/profile source from uploaded file "${file.name}":`,
          trimmed
        ]
          .filter(Boolean)
          .join("\n\n")
      );
      setAttachmentStatus(`${file.name} added to the command. Run command when ready.`);
    } catch {
      setAttachmentStatus(`${file.name} could not be read in the browser.`);
    }
  }

  return (
    <section className="ai-command-center" aria-labelledby="ai-command-center-title">
      <div className="command-center-header">
        <div>
          <p className="eyebrow">AI command center</p>
          <h1 id="ai-command-center-title">Ask JobOps to work across your search.</h1>
        </div>
        <span className="status-pill">FastAPI tool routing</span>
      </div>

      <div className="command-center-grid">
        <div className="command-conversation-frame">
          <div className="command-conversation" aria-label={transcriptLabel} onScroll={handleConversationScroll} ref={conversationRef}>
            {messages.map((message) => {
              const isStatus = isStatusMessage(message);
              return (
                <article className={`command-message ${message.role}${isStatus ? " status" : ""}`} key={message.id}>
                  {message.role === "user" ? <strong>You</strong> : null}
                  {message.role === "agent" && !isStatus ? (
                    <MarkdownMessage text={message.text} />
                  ) : (
                    <p>{message.text}</p>
                  )}
                </article>
              );
            })}
          </div>
          {hasNewMessagesBelow ? (
            <button className="command-scroll-latest" onClick={scrollConversationToBottom} type="button">
              &#8595;
              <span className="visually-hidden">Scroll to latest message</span>
            </button>
          ) : null}
        </div>

        <aside className="agent-action-rail" aria-label="Agent action cards">
          {actions.length > 0 ? (
            actions.slice(0, 3).map((action) => <AgentActionCard action={action} key={action.id} workspaceBasePath={workspaceBasePath} />)
          ) : (
            <div className="agent-action-empty">
              <h2>Planned actions</h2>
              <p>Submitted commands appear here as action cards after FastAPI routes or executes a tool.</p>
            </div>
          )}
        </aside>
      </div>

      <div className={`starter-prompts-panel${areExamplesExpanded ? " expanded" : ""}`}>
        <div className="starter-prompts-header">
          <span>Examples</span>
          <button
            aria-controls="jobops-starter-prompts"
            aria-expanded={areExamplesExpanded}
            aria-label={areExamplesExpanded ? "Hide starter prompt examples" : "Show starter prompt examples"}
            className="starter-prompts-toggle secondary-action"
            onClick={() => setAreExamplesExpanded((current) => !current)}
            suppressHydrationWarning
            type="button"
          >
            {areExamplesExpanded ? "Hide examples" : "Show examples"}
          </button>
        </div>
        <div className="starter-prompts" id="jobops-starter-prompts" aria-label="Starter prompts">
          {starterPrompts.map((prompt) => (
            <button className="starter-prompt" key={prompt} onClick={() => setCommand(prompt)} suppressHydrationWarning type="button">
              {prompt}
            </button>
          ))}
        </div>
      </div>

      <form className="command-composer" onSubmit={handleSubmit}>
        <label className="composer-label" htmlFor="jobops-command">
          Command
        </label>
        <textarea
          id="jobops-command"
          onChange={(event) => setCommand(event.target.value)}
          onKeyDown={handleCommandKeyDown}
          placeholder="Tell JobOps what changed, paste resume text, or ask what to prioritize."
          suppressHydrationWarning
          value={command}
        />
        <div className="command-composer-actions">
          <input
            accept=".txt,.md,.markdown,.rtf,.csv,.json,text/*"
            className="visually-hidden"
            onChange={handleFileChange}
            ref={fileInputRef}
            type="file"
          />
          <button className="secondary-action button-action" onClick={() => fileInputRef.current?.click()} type="button">
            Add file
          </button>
          <button className="primary-action button-action" disabled={isSubmitting} suppressHydrationWarning type="submit">
            {isSubmitting ? "Working..." : "Run command"}
          </button>
        </div>
        {attachmentStatus ? <p className="attachment-state">{attachmentStatus}</p> : null}
      </form>
    </section>
  );
}

function isScrolledNearBottom(element: HTMLElement) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= SCROLL_BOTTOM_THRESHOLD_PX;
}

function formatTranscriptMessage(message: string) {
  const compact = message.replace(/\s+/g, " ").trim();
  if (compact.length <= TRANSCRIPT_PREVIEW_MAX_CHARS) {
    return message;
  }

  return `Pasted message: ${summarizeCommandForDisplay(message, TRANSCRIPT_PREVIEW_MAX_CHARS)}`;
}

function truncateText(value: string, maxLength: number) {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return value;
  }

  return `${compact.slice(0, Math.max(0, maxLength - 3)).trimEnd()}...`;
}
function isTextUpload(file: File, extension: string) {
  return file.type.startsWith("text/") || ["txt", "md", "markdown", "rtf", "csv", "json"].includes(extension);
}

async function runCommandCenterStream({
  activeWorkspace,
  apiBasePath,
  clientContext,
  command,
  onStatus
}: {
  activeWorkspace?: WorkspaceTab;
  apiBasePath: string;
  clientContext?: Record<string, unknown>;
  command: string;
  onStatus: (statusUpdate: CommandCenterStatusUpdate) => void;
}): Promise<CommandCenterApiResponse> {
  const requestUrl = `${apiBasePath}/command-center/stream`;
  const response = await fetch(requestUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      command,
      activeWorkspace,
      clientContext
    })
  });

  if (!response.ok) {
    throw new Error(await readCommandCenterStreamError(response, requestUrl));
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/x-ndjson")) {
    const body = await response.text();
    logUnexpectedCommandCenterResponse({
      body,
      contentType,
      message: "Command-center stream returned a non-NDJSON response.",
      requestUrl,
      response
    });
    throw new Error("Command-center stream returned an unexpected response. Please refresh and sign in again.");
  }
  if (!response.body) {
    throw new Error("Command-center stream did not return a response body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: CommandCenterApiResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const event = parseCommandCenterStreamEvent(line);
      if (!event) {
        continue;
      }
      if (event.type === "status") {
        onStatus(event.statusUpdate);
      } else {
        result = event.result;
        return result;
      }
    }

    if (done) {
      break;
    }
  }

  const finalEvent = parseCommandCenterStreamEvent(buffer);
  if (finalEvent?.type === "status") {
    onStatus(finalEvent.statusUpdate);
  } else if (finalEvent?.type === "result") {
    result = finalEvent.result;
  }

  if (!result) {
    throw new Error("Command-center stream ended before returning a result.");
  }

  return result;
}

export function buildCommandCenterClientContext(messages: CommandMessage[], submittedCommand: string) {
  return {
    transcript: {
      source: "jobops_command_center_active_thread",
      messages: [
        ...messages.map(commandMessageToTranscriptMessage),
        {
          role: "user",
          type: "message",
          text: submittedCommand
        }
      ]
    }
  };
}

function commandMessageToTranscriptMessage(message: CommandMessage) {
  const isStatus = isStatusMessage(message);
  return {
    role: message.role === "user" ? "user" : "assistant",
    type: isStatus ? "status" : "message",
    text: message.rawText ?? message.text
  };
}

function isStatusMessage(message: CommandMessage) {
  return message.role === "agent" && message.text.startsWith("Status update:");
}

function parseCommandCenterStreamEvent(line: string): CommandCenterStreamEvent | null {
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }

  const parsed = JSON.parse(trimmed) as CommandCenterStreamEvent;
  if (parsed.type === "status" || parsed.type === "result") {
    return parsed;
  }
  return null;
}

function latestRoutedStreamStatus(statusUpdates: CommandCenterStatusUpdate[]) {
  for (let index = statusUpdates.length - 1; index >= 0; index -= 1) {
    const statusUpdate = statusUpdates[index];
    if (statusUpdate.actionType && statusUpdate.actionType !== "unknown") {
      return statusUpdate;
    }
  }
  return null;
}

function createInterruptedStreamAction(command: string, statusUpdate: CommandCenterStatusUpdate, id: string): PlannedCommandAction {
  const plannedAction = createPlannedAction(command, id);
  const workspace = statusUpdate.targetWorkspace ?? plannedAction.targetWorkspace;
  const workspaceLabel = workspace ? formatWorkspaceLabel(workspace) : "the command center";

  return {
    ...plannedAction,
    type: statusUpdate.actionType ?? plannedAction.type,
    status: "needs_confirmation",
    targetWorkspace: workspace ?? undefined,
    ctaLabel: workspace ? `Open ${workspaceLabel}` : plannedAction.ctaLabel,
    summary: `JobOps routed this command, but the browser stream ended before the final result arrived. The command was not replayed to avoid duplicate changes.`
  };
}

function createInterruptedFallbackAction(command: string, id: string): PlannedCommandAction {
  const plannedAction = createPlannedAction(command, id);

  return {
    ...plannedAction,
    status: "needs_confirmation",
    summary: `The command stream ended before the final result reached the browser. The command was not replayed to avoid duplicate changes.`
  };
}

function shouldAvoidFallbackReplay(action: PlannedCommandAction) {
  return action.type !== "unknown";
}

function getAsyncJobDiscoveryRunId(action: PlannedCommandAction) {
  if (action.type !== "job_discovery" || !isRecord(action.resultPayload)) {
    return null;
  }
  const payload = action.resultPayload;
  return payload.async === true && typeof payload.jobSearchRunId === "string" ? payload.jobSearchRunId : null;
}

async function fetchJobSearchRunStatus(runId: string, apiBasePath: string): Promise<JobSearchRunStatus> {
  const response = await fetch(`${apiBasePath}/job-search-runs/${encodeURIComponent(runId)}`, {
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error("Job search run status request failed.");
  }
  const payload = (await response.json()) as unknown;
  if (!isJobSearchRunStatus(payload)) {
    throw new Error("Job search run status response was invalid.");
  }
  return payload;
}

export function buildJobDiscoveryRunSummary(run: JobSearchRunStatus) {
  const modelSummary =
    cleanOptionalSummary(run.userVisibleSummary) ??
    cleanOptionalSummary(run.userSummary) ??
    cleanOptionalSummary(run.selectionAssistantMessage);
  if (modelSummary) {
    return modelSummary;
  }
  return `Job discovery completed: ${run.savedCount} new job(s) saved, ${run.updatedExistingCount} refreshed, ${run.duplicateCount} duplicate(s), ${run.skippedCount} skipped.`;
}

function cleanOptionalSummary(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readStoredJobDiscoveryRunId() {
  try {
    return window.sessionStorage.getItem(JOB_DISCOVERY_RUN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeJobDiscoveryRunId(runId: string) {
  try {
    window.sessionStorage.setItem(JOB_DISCOVERY_RUN_STORAGE_KEY, runId);
  } catch {
    // Session storage is a recovery aid; polling still works from component state.
  }
}

function clearStoredJobDiscoveryRunId(runId: string) {
  try {
    if (window.sessionStorage.getItem(JOB_DISCOVERY_RUN_STORAGE_KEY) === runId) {
      window.sessionStorage.removeItem(JOB_DISCOVERY_RUN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage failures.
  }
}

function isJobSearchRunStatus(value: unknown): value is JobSearchRunStatus {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === "string" &&
    typeof value.status === "string" &&
    typeof value.message === "string" &&
    typeof value.providerResultCount === "number" &&
    typeof value.candidatePoolCount === "number" &&
    typeof value.candidateCountAfterDedupe === "number" &&
    typeof value.modelSelectedCount === "number" &&
    typeof value.savedCount === "number" &&
    typeof value.updatedExistingCount === "number" &&
    typeof value.duplicateCount === "number" &&
    typeof value.skippedCount === "number" &&
    typeof value.providerErrorCount === "number"
  );
}

async function readCommandCenterStreamError(response: Response, requestUrl: string) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.toLowerCase().includes("application/json")) {
    try {
      const payload = (await response.json()) as CommandCenterProxyResponse;
      if (payload.ok) {
        return "Command-center stream request failed.";
      }
      throw new CommandCenterProxyError(payload.error);
    } catch (error) {
      if (isStructuredCommandCenterError(error)) {
        throw error;
      }
      return "Command-center stream returned an invalid error response.";
    }
  }
  const body = await response.text();
  logUnexpectedCommandCenterResponse({
    body,
    contentType,
    message: "Command-center stream returned a non-JSON error response.",
    requestUrl,
    response
  });
  return "Command-center stream returned an unexpected response. Please refresh and sign in again.";
}

async function readCommandCenterProxyResponse(response: Response, requestUrl: string): Promise<CommandCenterProxyResponse> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    const body = await response.text();
    logUnexpectedCommandCenterResponse({
      body,
      contentType,
      message: "Command-center fallback returned a non-JSON response.",
      requestUrl,
      response
    });
    throw new Error("Command-center returned a sign-in or error page instead of JSON. Please refresh and sign in again.");
  }

  const payload = (await response.json()) as CommandCenterProxyResponse;
  if (!payload.ok) {
    throw new CommandCenterProxyError(payload.error);
  }
  return payload;
}

function logUnexpectedCommandCenterResponse({
  body,
  contentType,
  message,
  requestUrl,
  response
}: {
  body: string;
  contentType: string;
  message: string;
  requestUrl: string;
  response: Response;
}) {
  console.error(message, {
    bodyPreview: previewDiagnosticBody(body),
    contentType: contentType || null,
    requestUrl,
    responseUrl: response.url || null,
    status: response.status
  });
}

function previewDiagnosticBody(body: string) {
  return body.replace(/\s+/g, " ").trim().slice(0, COMMAND_CENTER_DIAGNOSTIC_BODY_PREVIEW_CHARS);
}

class CommandCenterProxyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CommandCenterProxyError";
  }
}

function isStructuredCommandCenterError(error: unknown): error is CommandCenterProxyError {
  return error instanceof CommandCenterProxyError;
}

export function MarkdownMessage({ text }: { text: string }) {
  return <div className="command-message-markdown">{parseMarkdownBlocks(text).map(renderMarkdownBlock)}</div>;
}

type MarkdownBlock =
  | { type: "code"; content: string; language?: string; key: string }
  | { type: "heading"; depth: number; content: string; key: string }
  | { type: "list"; ordered: boolean; items: string[]; key: string }
  | { type: "paragraph"; content: string; key: string };

function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let listOrdered = false;
  let codeLines: string[] = [];
  let codeLanguage: string | undefined;
  let inCode = false;

  function flushParagraph() {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", content: paragraph.join(" "), key: `p-${blocks.length}` });
      paragraph = [];
    }
  }

  function flushList() {
    if (listItems.length > 0) {
      blocks.push({ type: "list", ordered: listOrdered, items: listItems, key: `l-${blocks.length}` });
      listItems = [];
    }
  }

  for (const line of lines) {
    const fence = line.match(/^```(\S*)\s*$/);
    if (fence) {
      if (inCode) {
        blocks.push({ type: "code", content: codeLines.join("\n"), language: codeLanguage, key: `c-${blocks.length}` });
        codeLines = [];
        codeLanguage = undefined;
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
        codeLanguage = fence[1] || undefined;
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", depth: heading[1].length, content: heading[2].trim(), key: `h-${blocks.length}` });
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    const listMatch = unordered ?? ordered;
    if (listMatch) {
      flushParagraph();
      const orderedLine = Boolean(ordered);
      if (listItems.length > 0 && listOrdered !== orderedLine) {
        flushList();
      }
      listOrdered = orderedLine;
      listItems.push(listMatch[1].trim());
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }

  if (inCode) {
    blocks.push({ type: "code", content: codeLines.join("\n"), language: codeLanguage, key: `c-${blocks.length}` });
  }
  flushParagraph();
  flushList();

  return blocks.length > 0 ? blocks : [{ type: "paragraph", content: "", key: "p-empty" }];
}

function renderMarkdownBlock(block: MarkdownBlock) {
  if (block.type === "code") {
    return (
      <pre key={block.key}>
        <code data-language={block.language}>{block.content}</code>
      </pre>
    );
  }
  if (block.type === "heading") {
    const content = renderInlineMarkdown(block.content);
    if (block.depth === 1) {
      return <h2 key={block.key}>{content}</h2>;
    }
    if (block.depth === 2) {
      return <h3 key={block.key}>{content}</h3>;
    }
    return <h4 key={block.key}>{content}</h4>;
  }
  if (block.type === "list") {
    const Tag = block.ordered ? "ol" : "ul";
    return (
      <Tag key={block.key}>
        {block.items.map((item, index) => (
          <li key={`${block.key}-${index}`}>{renderInlineMarkdown(item)}</li>
        ))}
      </Tag>
    );
  }
  return <p key={block.key}>{renderInlineMarkdown(block.content)}</p>;
}

function renderInlineMarkdown(source: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(source)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(source.slice(lastIndex, match.index));
    }

    const token = match[0];
    const key = `inline-${match.index}-${nodes.length}`;
    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={key}>{renderInlineMarkdown(token.slice(2, -2))}</strong>);
    } else if (token.startsWith("*")) {
      nodes.push(<em key={key}>{renderInlineMarkdown(token.slice(1, -1))}</em>);
    } else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const href = link ? safeMarkdownHref(link[2].trim()) : null;
      nodes.push(
        href ? (
          <a href={href} key={key} rel="noopener noreferrer" target="_blank">
            {renderInlineMarkdown(link?.[1] ?? "")}
          </a>
        ) : (
          token
        )
      );
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < source.length) {
    nodes.push(source.slice(lastIndex));
  }

  return nodes;
}

function safeMarkdownHref(rawHref: string) {
  try {
    const parsed = new URL(rawHref, "https://jobops.local");
    if (!SAFE_LINK_PROTOCOLS.has(parsed.protocol)) {
      return null;
    }
    return rawHref;
  } catch {
    return null;
  }
}

function AgentActionCard({ action, workspaceBasePath }: { action: PlannedCommandAction; workspaceBasePath: string }) {
  const modelRequest = getModelRequestDebugPayload(action.resultPayload);
  const modelResponse = getModelResponseDebugPayload(action.resultPayload);
  const jobDiscoveryDiagnostics = getJobDiscoveryDiagnostics(action.resultPayload);
  const jobDiscoveryJobs = getJobDiscoveryJobs(action.resultPayload);
  const noJobsAddedReason = getNoJobsAddedReason(action.resultPayload);
  const isBusyJobDiscovery = action.type === "job_discovery" && action.status === "running";

  return (
    <article className={`agent-action-card${isBusyJobDiscovery ? " agent-action-card-busy" : ""}`}>
      <div>
        <p className="eyebrow">{action.status.replace("_", " ")}</p>
        <h2>{action.title}</h2>
      </div>
      {isBusyJobDiscovery ? (
        <div className="agent-action-busy" role="status">
          <span aria-hidden="true" />
          <strong>Job discovery is running...</strong>
        </div>
      ) : null}
      <p>{truncateText(action.summary, ACTION_SUMMARY_MAX_CHARS)}</p>
      <div className="agent-action-meta">
        <span>{action.type}</span>
        {action.targetWorkspace ? <span>{formatWorkspaceLabel(action.targetWorkspace)}</span> : null}
      </div>
      {jobDiscoveryDiagnostics ? (
        <dl className="agent-action-diagnostics" aria-label="Job discovery diagnostics">
          {jobDiscoveryDiagnostics.map((item) => (
            <div key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {jobDiscoveryJobs.length ? (
        <section className="agent-action-jobs" aria-label="Recommended jobs">
          <h3>{jobDiscoveryJobsLabel(action.resultPayload)}</h3>
          <div>
            {jobDiscoveryJobs.slice(0, 5).map((job) => (
              <article className="agent-action-job-row" key={job.id}>
                <div>
                  <strong>{stringPayloadValue(job.title) || "Untitled role"}</strong>
                  <span>
                    {[
                      stringPayloadValue(job.company_name),
                      stringPayloadValue(job.location) || formatOptionalStatus(stringPayloadValue(job.remote_work_mode))
                    ]
                      .filter(Boolean)
                      .join(" - ")}
                  </span>
                  <small>
                    {[
                      formatOptionalStatus(
                        stringPayloadValue(job.source_provider) || stringPayloadValue(job.source) || stringPayloadValue(job.provider_type)
                      ),
                      formatOptionalStatus(stringPayloadValue(job.status))
                    ]
                      .filter(Boolean)
                      .join(" - ")}
                  </small>
                </div>
                {jobActionUrl(job) ? (
                  <a href={jobActionUrl(job) || "#"} rel="noopener noreferrer" target="_blank">
                    Open
                  </a>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ) : noJobsAddedReason ? (
        <p className="agent-action-no-jobs">No jobs added: {formatNoJobsAddedReason(noJobsAddedReason)}</p>
      ) : null}
      {modelRequest ? (
        <details className="model-request-debug">
          <summary>Sent to model</summary>
          <pre>{formatModelRequestDebugPayload(modelRequest)}</pre>
        </details>
      ) : null}
      {modelResponse ? (
        <details className="model-request-debug">
          <summary>Model response</summary>
          <pre>{formatModelRequestDebugPayload(modelResponse)}</pre>
        </details>
      ) : null}
      {action.targetWorkspace ? (
        <Link className="secondary-action agent-action-link" href={getWorkspaceRoute(action.targetWorkspace, workspaceBasePath)}>
          {action.ctaLabel ?? `Open ${formatWorkspaceLabel(action.targetWorkspace)}`}
        </Link>
      ) : (
        <span className="planned-affordance" aria-disabled="true">
          Planned
        </span>
      )}
    </article>
  );
}

function getJobDiscoveryDiagnostics(resultPayload: unknown) {
  if (!isRecord(resultPayload)) {
    return null;
  }
  const payload = resultPayload;
  if (!("jobDiscoveryMode" in payload || "providerResultCount" in payload || "skippedReasons" in payload)) {
    return null;
  }
  const diagnostics = [
    textDiagnostic("Mode", payload.jobDiscoveryMode),
    textDiagnostic("Source", payload.sourceName ?? payload.providerName),
    numberDiagnostic("DB matches", payload.databaseMatchedJobCount),
    numberDiagnostic("Reviewed", payload.jobsReviewedByModel),
    numberDiagnostic("Added to list", payload.addedToCandidateJobsList),
    numberDiagnostic("Provider results", payload.providerResultCount),
    numberDiagnostic("Model selected", payload.modelSelectedCount),
    numberDiagnostic("Verified URLs", payload.verifiedUrlCount ?? payload.verifiedCount),
    numberDiagnostic("Saved", payload.savedJobCount ?? payload.savedCount),
    numberDiagnostic("Duplicates", payload.duplicateCount),
    textDiagnostic("No jobs added", formatNoJobsAddedReason(getNoJobsAddedReason(payload))),
    skippedReasonsDiagnostic(payload.skippedReasons)
  ].filter((item): item is { label: string; value: string } => Boolean(item));
  return diagnostics.length ? diagnostics : null;
}

function getJobDiscoveryJobs(resultPayload: unknown): Array<Record<string, unknown> & { id: string }> {
  if (!isRecord(resultPayload)) {
    return [];
  }
  const rawJobs = Array.isArray(resultPayload.jobs)
    ? resultPayload.jobs
    : Array.isArray(resultPayload.addedJobs)
      ? resultPayload.addedJobs
      : [];
  return rawJobs.filter((job): job is Record<string, unknown> & { id: string } => isRecord(job) && typeof job.id === "string");
}

function getNoJobsAddedReason(resultPayload: unknown) {
  if (!isRecord(resultPayload)) {
    return null;
  }
  return typeof resultPayload.noJobsAddedReason === "string" && resultPayload.noJobsAddedReason ? resultPayload.noJobsAddedReason : null;
}

function stringPayloadValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function jobActionUrl(job: Record<string, unknown>) {
  return stringPayloadValue(job.apply_url) || stringPayloadValue(job.job_url) || stringPayloadValue(job.canonical_url) || null;
}

function jobDiscoveryJobsLabel(resultPayload: unknown) {
  if (!isRecord(resultPayload)) {
    return "Recommended jobs";
  }
  const runId = typeof resultPayload.jobSearchRunId === "string" ? resultPayload.jobSearchRunId : null;
  const highlightedRunId = typeof resultPayload.highlightedJobSearchRunId === "string" ? resultPayload.highlightedJobSearchRunId : null;
  if (runId && highlightedRunId && runId === highlightedRunId) {
    return "Just added to your jobs list";
  }
  return resultPayload.jobDiscoveryMode === "db_backed" ? "Recommended jobs" : "Jobs referenced by this response";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function textDiagnostic(label: string, value: unknown) {
  return typeof value === "string" && value ? { label, value } : null;
}

function numberDiagnostic(label: string, value: unknown) {
  return typeof value === "number" ? { label, value: String(value) } : null;
}

function formatOptionalStatus(value?: string | null) {
  if (!value) {
    return "";
  }
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatNoJobsAddedReason(value?: string | null) {
  if (!value) {
    return "";
  }
  const labels: Record<string, string> = {
    no_db_matches: "No synced jobs matched the database search",
    model_review_failed: "Model review did not complete",
    model_selected_zero: "Model review selected zero jobs",
    review_validation_removed_all_selected_ids: "Model returned job IDs outside the reviewed pool",
    all_selected_jobs_already_on_list: "Selected jobs were already on the jobs list",
    unknown: "Unknown"
  };
  return labels[value] ?? formatOptionalStatus(value);
}

function skippedReasonsDiagnostic(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const summary = Object.entries(value as Record<string, unknown>)
    .filter(([, count]) => typeof count === "number")
    .map(([reason, count]) => `${reason}: ${count}`)
    .join("; ");
  return summary ? { label: "Skipped", value: summary } : null;
}

function getModelRequestDebugPayload(resultPayload: unknown) {
  if (!resultPayload || typeof resultPayload !== "object" || Array.isArray(resultPayload)) {
    return null;
  }

  const payload = resultPayload as { modelRequest?: unknown };
  return payload.modelRequest ?? null;
}

function getModelResponseDebugPayload(resultPayload: unknown) {
  if (!resultPayload || typeof resultPayload !== "object" || Array.isArray(resultPayload)) {
    return null;
  }

  const payload = resultPayload as { modelResponse?: unknown };
  return payload.modelResponse ?? null;
}

function formatModelRequestDebugPayload(modelRequest: unknown) {
  try {
    return JSON.stringify(modelRequest, null, 2);
  } catch {
    return String(modelRequest);
  }
}

export { starterPrompts };
