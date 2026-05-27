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
import type { CommandCenterApiResponse, CommandCenterProxyResponse, CommandCenterStreamEvent } from "../lib/command-center-contract";

type CommandMessage = {
  id: string;
  role: "agent" | "user";
  text: string;
};

const starterPrompts = [
  "I want to be an Applied AI Engineer.",
  "Update my profile with this project.",
  "Find companies in progressive politics hiring AI engineers.",
  "Here's a job URL. Add it to my jobs list.",
  "Follow this company.",
  "Which jobs should I apply to today?",
  "Generate materials for this application."
];

const TRANSCRIPT_PREVIEW_MAX_CHARS = 520;
const ACTION_SUMMARY_MAX_CHARS = 360;
const SCROLL_BOTTOM_THRESHOLD_PX = 48;
const COMMAND_CENTER_DIAGNOSTIC_BODY_PREVIEW_CHARS = 200;

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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasNewMessagesBelow, setHasNewMessagesBelow] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);

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

    const submissionId = Date.now();
    setMessages((current) => [
      ...current,
      {
        id: `user-${submissionId}`,
        role: "user",
        text: formatTranscriptMessage(submittedCommand)
      },
      {
        id: `agent-status-submitted-${submissionId}`,
        role: "agent",
        text: "Status update: sending this command to the JobOps router."
      }
    ]);
    setCommand("");
    setIsSubmitting(true);

    try {
      const result = await runCommandCenterStream({
        activeWorkspace,
        apiBasePath,
        command: submittedCommand,
        onStatus: (message) => {
          setMessages((current) => [
            ...current,
            {
              id: `agent-status-${Date.now()}-${current.length}`,
              role: "agent",
              text: message
            }
          ]);
        }
      });

      applyCommandCenterResult(result);
    } catch (error) {
      try {
        const fallbackRequestUrl = `${apiBasePath}/command-center`;
        const response = await fetch(fallbackRequestUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            command: submittedCommand,
            activeWorkspace
          })
        });
        const payload = await readCommandCenterProxyResponse(response, fallbackRequestUrl);

        if (!response.ok || !payload.ok) {
          throw new Error(payload.ok ? "Command-center request failed." : payload.error);
        }

        applyCommandCenterResult(payload.result);
      } catch (fallbackError) {
        const fallbackAction = createPlannedAction(submittedCommand, `action-${Date.now()}`);
        const workspace = fallbackAction.targetWorkspace ? formatWorkspaceLabel(fallbackAction.targetWorkspace) : "Command Center";
        const message = fallbackError instanceof Error ? fallbackError.message : "Command-center API is unavailable.";

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
            {messages.map((message) => (
              <article className={`command-message ${message.role}`} key={message.id}>
                {message.role === "user" ? <strong>You</strong> : null}
                <p>{message.text}</p>
              </article>
            ))}
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

      <div className="starter-prompts" aria-label="Starter prompts">
        {starterPrompts.map((prompt) => (
          <button className="starter-prompt" key={prompt} onClick={() => setCommand(prompt)} suppressHydrationWarning type="button">
            {prompt}
          </button>
        ))}
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
  command,
  onStatus
}: {
  activeWorkspace?: WorkspaceTab;
  apiBasePath: string;
  command: string;
  onStatus: (message: string) => void;
}): Promise<CommandCenterApiResponse> {
  const requestUrl = `${apiBasePath}/command-center/stream`;
  const response = await fetch(requestUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      command,
      activeWorkspace
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
        onStatus(event.statusUpdate.message);
      } else {
        result = event.result;
      }
    }

    if (done) {
      break;
    }
  }

  const finalEvent = parseCommandCenterStreamEvent(buffer);
  if (finalEvent?.type === "status") {
    onStatus(finalEvent.statusUpdate.message);
  } else if (finalEvent?.type === "result") {
    result = finalEvent.result;
  }

  if (!result) {
    throw new Error("Command-center stream ended before returning a result.");
  }

  return result;
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

async function readCommandCenterStreamError(response: Response, requestUrl: string) {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.toLowerCase().includes("application/json")) {
    try {
      const payload = (await response.json()) as CommandCenterProxyResponse;
      return payload.ok ? "Command-center stream request failed." : payload.error;
    } catch {
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

  return (await response.json()) as CommandCenterProxyResponse;
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

function AgentActionCard({ action, workspaceBasePath }: { action: PlannedCommandAction; workspaceBasePath: string }) {
  const modelRequest = getModelRequestDebugPayload(action.resultPayload);
  const modelResponse = getModelResponseDebugPayload(action.resultPayload);

  return (
    <article className="agent-action-card">
      <div>
        <p className="eyebrow">{action.status.replace("_", " ")}</p>
        <h2>{action.title}</h2>
      </div>
      <p>{truncateText(action.summary, ACTION_SUMMARY_MAX_CHARS)}</p>
      <div className="agent-action-meta">
        <span>{action.type}</span>
        {action.targetWorkspace ? <span>{formatWorkspaceLabel(action.targetWorkspace)}</span> : null}
      </div>
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
