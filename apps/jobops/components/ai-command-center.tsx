"use client";

import Link from "next/link";
import React, { useMemo, useState } from "react";
import {
  createPlannedAction,
  formatWorkspaceLabel,
  getWorkspaceRoute,
  type PlannedCommandAction,
  type WorkspaceTab
} from "../lib/command-center-actions";
import type { CommandCenterProxyResponse } from "../lib/command-center-contract";

type CommandMessage = {
  id: string;
  role: "agent" | "user";
  text: string;
};

const starterPrompts = [
  "I want to be an Applied AI Engineer.",
  "Update my profile with this project.",
  "Here's a job URL. Add it to my jobs list.",
  "Follow this company.",
  "Which jobs should I apply to today?",
  "Generate materials for this application."
];

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
  const [isSubmitting, setIsSubmitting] = useState(false);

  const latestAction = actions[0];
  const transcriptLabel = useMemo(
    () => (latestAction ? `Latest planned action: ${latestAction.title}` : "Command history"),
    [latestAction]
  );

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const submittedCommand = command.trim();
    if (!submittedCommand) {
      return;
    }

    setMessages((current) => [
      ...current,
      {
        id: `user-${current.length + 1}`,
        role: "user",
        text: submittedCommand
      }
    ]);
    setCommand("");
    setIsSubmitting(true);

    try {
      const response = await fetch(`${apiBasePath}/command-center`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          command: submittedCommand,
          activeWorkspace
        })
      });
      const payload = (await response.json()) as CommandCenterProxyResponse;

      if (!response.ok || !payload.ok) {
        throw new Error(payload.ok ? "Command-center request failed." : payload.error);
      }

      const nextActions = payload.result.actions.map((action, index) => ({
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
          text: payload.result.assistant_message
        }
      ]);

      if (nextActions.some((action) => action.type === "profile_intake" && action.status === "completed")) {
        window.dispatchEvent(new CustomEvent("jobops:profile-draft-updated"));
      }
    } catch (error) {
      const fallbackAction = createPlannedAction(submittedCommand, `action-${Date.now()}`);
      const workspace = fallbackAction.targetWorkspace ? formatWorkspaceLabel(fallbackAction.targetWorkspace) : "Command Center";
      const message = error instanceof Error ? error.message : "Command-center API is unavailable.";

      setActions((current) => [fallbackAction, ...current]);
      setMessages((current) => [
        ...current,
        {
          id: `agent-${current.length + 1}`,
          role: "agent",
          text: `${message} I kept a local fallback action for ${workspace}.`
        }
      ]);
    } finally {
      setIsSubmitting(false);
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
        <div className="command-conversation" aria-label={transcriptLabel}>
          {messages.slice(-4).map((message) => (
            <article className={`command-message ${message.role}`} key={message.id}>
              <strong>{message.role === "agent" ? "JobOps agent" : "You"}</strong>
              <p>{message.text}</p>
            </article>
          ))}
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
          placeholder="Tell JobOps what changed, paste resume text, or ask what to prioritize."
          suppressHydrationWarning
          value={command}
        />
        <button className="primary-action button-action" disabled={isSubmitting} suppressHydrationWarning type="submit">
          {isSubmitting ? "Working..." : "Run command"}
        </button>
      </form>
    </section>
  );
}

function AgentActionCard({ action, workspaceBasePath }: { action: PlannedCommandAction; workspaceBasePath: string }) {
  return (
    <article className="agent-action-card">
      <div>
        <p className="eyebrow">{action.status.replace("_", " ")}</p>
        <h2>{action.title}</h2>
      </div>
      <p>{action.summary}</p>
      <div className="agent-action-meta">
        <span>{action.type}</span>
        {action.targetWorkspace ? <span>{formatWorkspaceLabel(action.targetWorkspace)}</span> : null}
      </div>
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

export { starterPrompts };
