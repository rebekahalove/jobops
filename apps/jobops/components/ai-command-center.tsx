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

    try {
      const result = await runCommandCenterStream({
        activeWorkspace,
        apiBasePath,
        clientContext,
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
  if (!resultPayload || typeof resultPayload !== "object" || Array.isArray(resultPayload)) {
    return null;
  }
  const payload = resultPayload as Record<string, unknown>;
  if (!("jobDiscoveryMode" in payload || "providerResultCount" in payload || "skippedReasons" in payload)) {
    return null;
  }
  const diagnostics = [
    textDiagnostic("Mode", payload.jobDiscoveryMode),
    textDiagnostic("Source", payload.sourceName ?? payload.providerName),
    numberDiagnostic("Provider results", payload.providerResultCount),
    numberDiagnostic("Verified URLs", payload.verifiedUrlCount ?? payload.verifiedCount),
    numberDiagnostic("Saved", payload.savedJobCount ?? payload.savedCount),
    numberDiagnostic("Duplicates", payload.duplicateCount),
    skippedReasonsDiagnostic(payload.skippedReasons)
  ].filter((item): item is { label: string; value: string } => Boolean(item));
  return diagnostics.length ? diagnostics : null;
}

function textDiagnostic(label: string, value: unknown) {
  return typeof value === "string" && value ? { label, value } : null;
}

function numberDiagnostic(label: string, value: unknown) {
  return typeof value === "number" ? { label, value: String(value) } : null;
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
