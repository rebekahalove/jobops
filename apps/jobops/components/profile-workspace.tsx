"use client";

import React, { type ChangeEvent, type FormEvent, useState } from "react";
import type { ProfileIntakeOutput } from "../lib/profile-intake-contract";
import {
  applyProfileIntakeOutputToState,
  emptyTargetRoleIntent,
  initialProfilePrompt,
  type MockIntakeTurn,
  type MockProfileDraft,
  type MockResumeAttachment,
  type TargetRoleIntent
} from "../lib/profile-intake";

type IntentField = keyof TargetRoleIntent;

type ChatMessage = {
  id: string;
  role: "agent" | "user";
  text: string;
  attachmentName?: string;
};

const initialMessages: ChatMessage[] = [
  {
    id: "agent-0",
    role: "agent",
    text: "Complete the sentence below with what you want to do next. After that, paste your resume into this same chat or attach it here, and I will turn it into draft profile data for review."
  }
];

export function ProfileWorkspace() {
  const [intent, setIntent] = useState<TargetRoleIntent>(emptyTargetRoleIntent);
  const [messageText, setMessageText] = useState(initialProfilePrompt);
  const [attachedResumeText, setAttachedResumeText] = useState("");
  const [attachment, setAttachment] = useState<MockResumeAttachment | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [draft, setDraft] = useState<MockProfileDraft | null>(null);
  const [lastTurn, setLastTurn] = useState<MockIntakeTurn | null>(null);
  const [editedFields, setEditedFields] = useState<Set<IntentField>>(() => new Set());
  const [isChangeExpanded, setIsChangeExpanded] = useState(false);
  const [isReviewExpanded, setIsReviewExpanded] = useState(false);
  const [isQuestionsExpanded, setIsQuestionsExpanded] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function updateIntent(field: IntentField, value: string) {
    setIntent((current) => ({
      ...current,
      [field]: value
    }));
    setEditedFields((current) => new Set(current).add(field));
  }

  async function attachResume(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    if (!file) {
      setAttachment(null);
      setAttachedResumeText("");
      return;
    }

    const nextAttachment: MockResumeAttachment = {
      name: file.name,
      sizeLabel: formatFileSize(file.size),
      parseStatus: canReadTextFile(file) ? "text_loaded" : "metadata_only"
    };

    setAttachment(nextAttachment);
    setAttachedResumeText("");

    if (canReadTextFile(file)) {
      setAttachedResumeText((await file.text()).slice(0, 30_000));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const submittedMessage = messageText.trim() || initialProfilePrompt;
    const modelMessage = [submittedMessage, attachedResumeText ? `Attached resume text:\n${attachedResumeText}` : ""]
      .filter(Boolean)
      .join("\n\n");
    const turnNumber = messages.length + 1;

    setIsSubmitting(true);

    try {
      const response = await fetch("/api/profile-intake", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          latestUserMessage: modelMessage,
          existingDraft: draft
        })
      });
      const payload = (await response.json()) as
        | { ok: true; result: ProfileIntakeOutput }
        | { ok: false; error: string; issues?: string[]; code?: string };

      if (!response.ok || !payload.ok) {
        const detail = !payload.ok && payload.issues?.length ? ` ${payload.issues.join(" ")}` : "";
        const hint = !payload.ok && payload.code?.startsWith("MODEL_CONFIG") ? ` ${modelConfigurationHint}` : "";
        throw new Error(`${payload.ok ? "Profile intake failed." : payload.error}${detail}${hint}`);
      }

      const nextState = applyProfileIntakeOutputToState(intent, payload.result);

      setIntent(nextState.intent);
      setDraft(nextState.draft);
      setLastTurn(nextState.turn);
      setMessages((current) => [
        ...current,
        {
          id: `user-${turnNumber}`,
          role: "user",
          text: submittedMessage,
          attachmentName: attachment?.name
        },
        {
          id: `agent-${turnNumber}`,
          role: "agent",
          text: nextState.turn.agentMessage
        }
      ]);
      setMessageText("");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Profile intake failed.";
      setMessages((current) => [
        ...current,
        {
          id: `user-${turnNumber}`,
          role: "user",
          text: submittedMessage,
          attachmentName: attachment?.name
        },
        {
          id: `agent-${turnNumber}`,
          role: "agent",
          text: message
        }
      ]);
      setMessageText("");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="dashboard-main profile-workspace">
      <section className="page-heading" aria-labelledby="profile-title">
        <p className="eyebrow">Profile workspace</p>
        <h1 id="profile-title">Build your JobOps profile through conversation.</h1>
        <p>
          The conversation drafts profile data. The review area below is where draft claims become edited, verified,
          private, public, or rejected later.
        </p>
      </section>

      <section className="chat-intake-panel" aria-labelledby="conversation-title">
        <div className="chat-panel-header">
          <div>
            <p className="eyebrow">Conversation-first intake</p>
            <h2 id="conversation-title">Start with what you want to do next.</h2>
          </div>
          <span className="status-pill">Server model intake</span>
        </div>

        <div className="chat-transcript" aria-label="Profile intake conversation">
          {messages.map((message) => (
            <article className={`chat-message ${message.role}`} key={message.id}>
              <strong>{message.role === "agent" ? "JobOps intake" : "You"}</strong>
              <p>{message.text}</p>
              {message.attachmentName ? <small>Attached: {message.attachmentName}</small> : null}
            </article>
          ))}
        </div>

        <form className="chat-composer" onSubmit={handleSubmit}>
          <label className="composer-label" htmlFor="profile-message">
            Message
          </label>
          <textarea
            id="profile-message"
            onChange={(event) => setMessageText(event.target.value)}
            placeholder="Complete the sentence, or paste your resume text here."
            suppressHydrationWarning
            value={messageText}
          />

          <div className="composer-actions">
            <label className="attachment-button">
              + Attach resume
              <input
                accept=".txt,.md,.pdf,.doc,.docx"
                className="visually-hidden"
                onChange={attachResume}
                suppressHydrationWarning
                type="file"
              />
            </label>
            <button className="primary-action button-action" disabled={isSubmitting} suppressHydrationWarning type="submit">
              {isSubmitting ? "Reading..." : "Send to intake agent"}
            </button>
          </div>

          <div className="attachment-state" aria-live="polite">
            {attachment ? (
              <span>
                {attachment.name} ({attachment.sizeLabel}) / {attachment.parseStatus}
              </span>
            ) : (
              <span>Paste resume text into the message box, or attach a resume file.</span>
            )}
          </div>
        </form>
      </section>

      <CollapsiblePanel
        eyebrow="Latest agent turn"
        expanded={isChangeExpanded}
        id="change-summary-title"
        onToggle={() => setIsChangeExpanded((current) => !current)}
        subtitle="Every generated change remains a private draft until reviewed."
        title="What changed"
      >
        <ChangeSummary turn={lastTurn} />
      </CollapsiblePanel>

      <CollapsiblePanel
        aside={
          <div className="profile-status-bar" aria-label="Profile-level statuses">
            <span>
              <strong>Review</strong>
              Needs verification
            </span>
            <span>
              <strong>Visibility</strong>
              Private
            </span>
            <span>
              <strong>Publication</strong>
              Not published
            </span>
          </div>
        }
        className="review-shell"
        eyebrow="Structured review"
        expanded={isReviewExpanded}
        id="review-title"
        onToggle={() => setIsReviewExpanded((current) => !current)}
        subtitle="These fields are updated by the conversation and can be edited before verification."
        title="Review & verify profile data"
      >
        <p className="status-context">
          The status bar applies to the profile overall. Badges beside fields and draft items describe field-level
          review state.
        </p>

        <section className="review-subsection" aria-labelledby="intent-review-title">
          <div>
            <h3 id="intent-review-title">Target role intent</h3>
          </div>
          <div className="intent-form review-form" aria-label="Target role intent review form">
            <IntentFieldControl
              editedFields={editedFields}
              field="targetTitles"
              label="Target titles"
              onChange={updateIntent}
              placeholder="Applied AI Engineer, Forward Deployed Engineer"
              value={intent.targetTitles}
            />
            <IntentFieldControl
              editedFields={editedFields}
              field="roleFamilies"
              label="Target role families"
              onChange={updateIntent}
              placeholder="LLM systems, product engineering, evals"
              value={intent.roleFamilies}
            />
            <label>
              <FieldLabel edited={editedFields.has("preferredWorkMode")} label="Preferred work mode" />
              <select
                onChange={(event) => updateIntent("preferredWorkMode", event.target.value)}
                suppressHydrationWarning
                value={intent.preferredWorkMode}
              >
                <option value="flexible">Flexible</option>
                <option value="remote">Remote</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">Onsite</option>
              </select>
            </label>
            <IntentFieldControl
              editedFields={editedFields}
              field="preferredLocations"
              label="Preferred locations"
              onChange={updateIntent}
              placeholder="Remote US, Raleigh-Durham, NYC"
              value={intent.preferredLocations}
            />
            <IntentFieldControl
              editedFields={editedFields}
              field="domainsOfInterest"
              label="Domains or industries of interest"
              onChange={updateIntent}
              placeholder="Developer tools, education, healthcare, enterprise AI"
              value={intent.domainsOfInterest}
            />
            <label>
              <FieldLabel edited={editedFields.has("constraints")} label="Dealbreakers or constraints" />
              <textarea
                className="small-textarea"
                onChange={(event) => updateIntent("constraints", event.target.value)}
                placeholder="Travel, location, timeline, role scope, sponsorship, compensation constraints"
                suppressHydrationWarning
                value={intent.constraints}
              />
            </label>
          </div>
        </section>

        <section className="review-subsection" aria-labelledby="draft-preview-title">
          <div>
            <h3 id="draft-preview-title">Draft review queues</h3>
            <p>Draft items are grouped by information type and need review before they become verified private data.</p>
          </div>
          <DraftProfilePreview draft={draft} />
        </section>

      </CollapsiblePanel>

      <CollapsiblePanel
        eyebrow="Follow-up queue"
        expanded={isQuestionsExpanded}
        id="questions-title"
        onToggle={() => setIsQuestionsExpanded((current) => !current)}
        subtitle="The conversation should pull these answers forward over time."
        title="Clarifying questions"
      >
        <ClarifyingQuestions draft={draft} />
      </CollapsiblePanel>
    </main>
  );
}

const modelConfigurationHint =
  "Switch to JOBOPS_LLM_PROVIDER=mock for deterministic local mode, or configure GEMINI_API_KEY for live Gemini mode.";

function CollapsiblePanel({
  aside,
  children,
  className,
  eyebrow,
  expanded,
  id,
  onToggle,
  subtitle,
  title
}: {
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  eyebrow: string;
  expanded: boolean;
  id: string;
  onToggle: () => void;
  subtitle: string;
  title: string;
}) {
  return (
    <section className={`collapsible-panel${className ? ` ${className}` : ""}`} aria-labelledby={id}>
      <div className="collapsible-header">
        <div className="collapsible-title">
          <p className="eyebrow">{eyebrow}</p>
          <h2 id={id}>{title}</h2>
        </div>
        <div className="collapsible-actions">
          {aside}
          <button
            aria-expanded={expanded}
            aria-label={`${expanded ? "Collapse" : "Expand"} ${title}`}
            className="collapse-button"
            onClick={onToggle}
            suppressHydrationWarning
            type="button"
          >
            {expanded ? "-" : "+"}
          </button>
        </div>
      </div>
      {expanded ? (
        <div className="collapsible-body">
          <p>{subtitle}</p>
          {children}
        </div>
      ) : null}
    </section>
  );
}

function IntentFieldControl({
  editedFields,
  field,
  label,
  onChange,
  placeholder,
  value
}: {
  editedFields: Set<IntentField>;
  field: IntentField;
  label: string;
  onChange: (field: IntentField, value: string) => void;
  placeholder: string;
  value: string;
}) {
  return (
    <label>
      <FieldLabel edited={editedFields.has(field)} label={label} />
      <input
        onChange={(event) => onChange(field, event.target.value)}
        placeholder={placeholder}
        suppressHydrationWarning
        value={value}
      />
    </label>
  );
}

function FieldLabel({ edited, label }: { edited: boolean; label: string }) {
  return (
    <span className="field-label">
      {label}
      <span className="field-badges">
        <span>{edited ? "Edited by you" : "Agent draft"}</span>
        <span>Needs review</span>
      </span>
    </span>
  );
}

function ChangeSummary({ turn }: { turn: MockIntakeTurn | null }) {
  if (!turn) {
    return (
      <div className="empty-state-block">
        <h3>No changes yet</h3>
        <p>Send a message or attach a resume to generate the first local summary.</p>
      </div>
    );
  }

  return (
    <div className="change-summary">
      <p>{turn.changeHeadline}</p>
      <details>
        <summary>View change notes</summary>
        <ul className="change-list">
          {turn.changeSummary.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function DraftProfilePreview({ draft }: { draft: MockProfileDraft | null }) {
  if (!draft) {
    return (
      <div className="profile-preview-grid">
        <PreviewColumn count={0} title="Experience & Projects">
          <li>No work, project, or education items drafted yet.</li>
        </PreviewColumn>
        <PreviewColumn count={0} title="Education">
          <li>No education items drafted yet.</li>
        </PreviewColumn>
        <PreviewColumn count={0} title="Certifications">
          <li>No certification items drafted yet.</li>
        </PreviewColumn>
        <PreviewColumn count={0} title="Skills">
          <li>No skill claims detected yet.</li>
        </PreviewColumn>
        <PreviewColumn count={0} title="Achievements / Outcomes">
          <li>No achievement or outcome items drafted yet.</li>
        </PreviewColumn>
        <PreviewColumn count={0} title="Facts / Claims">
          <li>No draft yet. Use the conversation panel to draft profile facts.</li>
        </PreviewColumn>
        <PreviewColumn count={0} title="Evidence & Links">
          <li>No links detected.</li>
        </PreviewColumn>
      </div>
    );
  }

  return (
    <div className="profile-preview-grid">
      <PreviewColumn count={draft.experienceSummaries.length} title="Experience & Projects">
        {draft.experienceSummaries.length ? (
          draft.experienceSummaries.slice(0, 2).map((experience) => (
            <li key={experience.id}>
              <strong>{experience.title}</strong>
              <span>{experience.summary}</span>
              <StatusBadges source={experience.source} />
            </li>
          ))
        ) : (
          <li>No past work, project, education, or artifact evidence detected yet.</li>
        )}
        <OverflowNote count={draft.experienceSummaries.length} noun="experience/project item" />
      </PreviewColumn>

      <PreviewColumn count={0} title="Education">
        <li>No education items detected by the mock extractor.</li>
      </PreviewColumn>

      <PreviewColumn count={0} title="Certifications">
        <li>No certification items detected by the mock extractor.</li>
      </PreviewColumn>

      <PreviewColumn count={draft.skillClaims.length} title="Skills">
        {draft.skillClaims.length ? (
          draft.skillClaims.slice(0, 2).map((skill) => (
            <li key={skill.id}>
              <strong>{skill.skill}</strong>
              <span>{skill.evidence}</span>
              <StatusBadges source={skill.source} />
            </li>
          ))
        ) : (
          <li>No skill claims detected by the mock extractor.</li>
        )}
        <OverflowNote count={draft.skillClaims.length} noun="skill claim" />
      </PreviewColumn>

      <PreviewColumn count={0} title="Achievements / Outcomes">
        <li>No achievement or outcome items detected by the mock extractor.</li>
      </PreviewColumn>

      <PreviewColumn count={draft.facts.length} title="Facts / Claims">
        {draft.facts.slice(0, 2).map((fact) => (
          <li key={fact.id}>
            <strong>{fact.category}</strong>
            <span>{fact.claim}</span>
            <StatusBadges source={fact.source} />
          </li>
        ))}
        <OverflowNote count={draft.facts.length} noun="draft fact" />
      </PreviewColumn>

      <PreviewColumn count={draft.links.length} title="Evidence & Links">
        {draft.links.length ? (
          draft.links.slice(0, 2).map((link) => (
            <li key={link.id}>
              <span>{link.label}</span>
              <span className="badge-row">
                <span>Needs review</span>
                <span>Private</span>
                <span>{sourceLabel(link.source)}</span>
              </span>
            </li>
          ))
        ) : (
          <li>No links detected.</li>
        )}
        <OverflowNote count={draft.links.length} noun="evidence item" />
      </PreviewColumn>
    </div>
  );
}

export function ClarifyingQuestions({ draft }: { draft: MockProfileDraft | null }) {
  if (!draft) {
    return (
      <div className="empty-state-block">
        <h3>No questions yet</h3>
        <p>The intake agent will queue applied AI and FDE-oriented questions after the first turn.</p>
      </div>
    );
  }

  return (
    <div>
      <p className="compact-label">Suggested next questions</p>
      <ol className="question-list compact-question-list">
      {draft.clarifyingQuestions.map((question) => (
        <li key={question.id}>{question.question}</li>
      ))}
      </ol>
    </div>
  );
}

function PreviewColumn({ children, count, title }: { children: React.ReactNode; count: number; title: string }) {
  return (
    <section className="preview-column">
      <div className="preview-column-header">
        <h3>{title}</h3>
        <span>{count}</span>
      </div>
      <ul>{children}</ul>
    </section>
  );
}

function StatusBadges({ source }: { source: MockProfileDraft["facts"][number]["source"] }) {
  return (
    <span className="badge-row">
      <span>Needs review</span>
      <span>Private</span>
      <span>{sourceLabel(source)}</span>
    </span>
  );
}

function sourceLabel(source: MockProfileDraft["facts"][number]["source"]) {
  return source === "resume" ? "Source: Resume" : source === "model" ? "Source: Model" : "Source: Chat";
}

function OverflowNote({ count, noun }: { count: number; noun: string }) {
  if (count <= 2) {
    return null;
  }

  return (
    <li className="overflow-note">
      +{count - 2} more {noun}
      {count - 2 === 1 ? "" : "s"} in this draft.
    </li>
  );
}

function canReadTextFile(file: File) {
  return file.type.startsWith("text/") || /\.(txt|md)$/i.test(file.name);
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  const kilobytes = bytes / 1024;

  if (kilobytes < 1024) {
    return `${kilobytes.toFixed(1)} KB`;
  }

  return `${(kilobytes / 1024).toFixed(1)} MB`;
}
