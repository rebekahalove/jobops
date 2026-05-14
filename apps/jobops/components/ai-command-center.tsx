"use client";

import Link from "next/link";
import React, { useMemo, useState } from "react";
import {
  createPlannedAction,
  formatWorkspaceLabel,
  workspaceRoutes,
  type PlannedCommandAction
} from "../lib/command-center-actions";

type CommandMessage = {
  id: string;
  role: "agent" | "user";
  text: string;
};

const starterPrompts = [
  "Here's a job URL. Add it to my jobs list.",
  "Follow this company.",
  "Which jobs should I apply to today?",
  "Prioritize my saved jobs.",
  "Generate materials for this application.",
  "What should I follow up on this week?"
];

const initialMessages: CommandMessage[] = [
  {
    id: "agent-0",
    role: "agent",
    text: "Tell JobOps what you want to move forward. I will plan the action and route it to the right workspace."
  }
];

export function AiCommandCenter({ initialActions = [] }: { initialActions?: PlannedCommandAction[] }) {
  const [command, setCommand] = useState("");
  const [messages, setMessages] = useState<CommandMessage[]>(initialMessages);
  const [actions, setActions] = useState<PlannedCommandAction[]>(initialActions);

  const latestAction = actions[0];
  const transcriptLabel = useMemo(
    () => (latestAction ? `Latest planned action: ${latestAction.title}` : "Command history"),
    [latestAction]
  );

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const submittedCommand = command.trim();
    if (!submittedCommand) {
      return;
    }

    // TODO: Real command handling should go through FastAPI. FastAPI owns agent routing,
    // tool execution, model calls, job URL intake, company follow, fit analysis, and materials generation.
    const action = createPlannedAction(submittedCommand, `action-${Date.now()}`);
    const workspace = action.targetWorkspace ? formatWorkspaceLabel(action.targetWorkspace) : "Command Center";

    setActions((current) => [action, ...current]);
    setMessages((current) => [
      ...current,
      {
        id: `user-${current.length + 1}`,
        role: "user",
        text: submittedCommand
      },
      {
        id: `agent-${current.length + 2}`,
        role: "agent",
        text: `${action.title} planned for ${workspace}. Execution is mocked in this shell branch.`
      }
    ]);
    setCommand("");
  }

  return (
    <section className="ai-command-center" aria-labelledby="ai-command-center-title">
      <div className="command-center-header">
        <div>
          <p className="eyebrow">AI command center</p>
          <h1 id="ai-command-center-title">Ask JobOps to work across your search.</h1>
        </div>
        <span className="status-pill">Local planning mock</span>
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
            actions.slice(0, 3).map((action) => <AgentActionCard action={action} key={action.id} />)
          ) : (
            <div className="agent-action-empty">
              <h2>Planned actions</h2>
              <p>Submitted commands will appear here as local action cards before backend execution exists.</p>
            </div>
          )}
        </aside>
      </div>

      <div className="starter-prompts" aria-label="Starter prompts">
        {starterPrompts.map((prompt) => (
          <button className="starter-prompt" key={prompt} onClick={() => setCommand(prompt)} type="button">
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
          placeholder="Paste a job URL, ask what to prioritize, or tell JobOps what changed."
          suppressHydrationWarning
          value={command}
        />
        <button className="primary-action button-action" suppressHydrationWarning type="submit">
          Plan action
        </button>
      </form>
    </section>
  );
}

function AgentActionCard({ action }: { action: PlannedCommandAction }) {
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
        <Link className="secondary-action agent-action-link" href={workspaceRoutes[action.targetWorkspace]}>
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
