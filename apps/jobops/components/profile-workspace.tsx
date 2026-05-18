"use client";

import React, { useEffect, useState } from "react";
import type { ProfileIntakeOutput } from "../lib/profile-intake-contract";
import {
  applyProfileIntakeOutputToState,
  emptyTargetRoleIntent,
  type MockIntakeTurn,
  type MockProfileDraft,
  type TargetRoleIntent
} from "../lib/profile-intake";

type IntentField = keyof TargetRoleIntent;
type ReviewTabId =
  | "experience"
  | "skills"
  | "achievements"
  | "facts"
  | "evidence"
  | "education"
  | "certifications";

const reviewTabs: Array<{ id: ReviewTabId; label: string }> = [
  { id: "experience", label: "Experience & Projects" },
  { id: "skills", label: "Skills" },
  { id: "achievements", label: "Achievements & Outcomes" },
  { id: "facts", label: "Facts & Claims" },
  { id: "evidence", label: "Evidence & Links" },
  { id: "education", label: "Education" },
  { id: "certifications", label: "Certifications" }
];

export function ProfileWorkspace({ apiBasePath = "/api" }: { apiBasePath?: string }) {
  const [intent, setIntent] = useState<TargetRoleIntent>(emptyTargetRoleIntent);
  const [draft, setDraft] = useState<MockProfileDraft | null>(null);
  const [lastTurn, setLastTurn] = useState<MockIntakeTurn | null>(null);
  const [editedFields, setEditedFields] = useState<Set<IntentField>>(() => new Set());
  const [isChangeExpanded, setIsChangeExpanded] = useState(true);
  const [isReviewExpanded, setIsReviewExpanded] = useState(true);
  const [isQuestionsExpanded, setIsQuestionsExpanded] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadLatestDraft() {
      try {
        const response = await fetch(`${apiBasePath}/profile-draft`);
        const payload = (await response.json()) as
          | { ok: true; result: ProfileIntakeOutput & { statusSummary?: string } }
          | { ok: false; error: string };

        if (cancelled) {
          return;
        }

        if (!response.ok || !payload.ok) {
          return;
        }

        const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, payload.result);
        setIntent(nextState.intent);
        setDraft(nextState.draft);
        setLastTurn(nextState.turn);
      } catch {
        return;
      }
    }

    function refreshLatestDraft() {
      void loadLatestDraft();
    }

    void loadLatestDraft();
    window.addEventListener("jobops:profile-draft-updated", refreshLatestDraft);

    return () => {
      cancelled = true;
      window.removeEventListener("jobops:profile-draft-updated", refreshLatestDraft);
    };
  }, [apiBasePath]);

  function updateIntent(field: IntentField, value: string) {
    setIntent((current) => ({
      ...current,
      [field]: value
    }));
    setEditedFields((current) => new Set(current).add(field));
  }

  return (
    <main className="dashboard-main profile-workspace">
      <section className="page-heading" aria-labelledby="profile-title">
        <p className="eyebrow">Profile workspace</p>
        <h1 id="profile-title">Review your JobOps profile draft.</h1>
        <p>
          Use the JobOps command center above to update your profile. This workspace shows the saved draft profile state
          for review, correction, and later verification.
        </p>
      </section>

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
        subtitle="These fields are updated from command-center profile intake and can be edited before verification."
        title="Review & verify profile data"
      >
        <p className="status-context">
          The status bar applies to the profile overall. Badges beside fields and draft items describe field-level
          review state.
        </p>

        <section className="review-subsection" aria-labelledby="current-draft-title">
          <div>
            <h3 id="current-draft-title">Current Draft</h3>
            <p>Draft items are grouped by information type and need review before they become verified private data.</p>
          </div>
          <div className="current-draft-stack">
            <TargetsCard editedFields={editedFields} intent={intent} onChange={updateIntent} />
            <DraftProfilePreview draft={draft} />
          </div>
        </section>

      </CollapsiblePanel>

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
        eyebrow="Follow-up queue"
        expanded={isQuestionsExpanded}
        id="questions-title"
        onToggle={() => setIsQuestionsExpanded((current) => !current)}
        subtitle="Command-center profile intake should pull these answers forward over time."
        title="Clarifying questions"
      >
        <ClarifyingQuestions draft={draft} />
      </CollapsiblePanel>
    </main>
  );
}

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

function TargetsCard({
  editedFields,
  intent,
  onChange
}: {
  editedFields: Set<IntentField>;
  intent: TargetRoleIntent;
  onChange: (field: IntentField, value: string) => void;
}) {
  return (
    <section className="profile-review-card target-settings-card" aria-labelledby="target-settings-title">
      <div>
        <p className="eyebrow">Draft settings</p>
        <h4 id="target-settings-title">Targets</h4>
      </div>
      <div className="intent-form review-form" aria-label="Target settings review form">
        <IntentFieldControl
          editedFields={editedFields}
          field="targetTitles"
          label="Target titles"
          onChange={onChange}
          placeholder="Applied AI Engineer, Forward Deployed Engineer"
          value={intent.targetTitles}
        />
        <IntentFieldControl
          editedFields={editedFields}
          field="roleFamilies"
          label="Target role families"
          onChange={onChange}
          placeholder="LLM systems, product engineering, evals"
          value={intent.roleFamilies}
        />
        <label>
          <FieldLabel edited={editedFields.has("preferredWorkMode")} label="Preferred work mode" />
          <select
            onChange={(event) => onChange("preferredWorkMode", event.target.value)}
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
          onChange={onChange}
          placeholder="Remote US, Raleigh-Durham, NYC"
          value={intent.preferredLocations}
        />
        <IntentFieldControl
          editedFields={editedFields}
          field="domainsOfInterest"
          label="Domains or industries of interest"
          onChange={onChange}
          placeholder="Developer tools, education, healthcare, enterprise AI"
          value={intent.domainsOfInterest}
        />
        <label>
          <FieldLabel edited={editedFields.has("constraints")} label="Dealbreakers or constraints" />
          <textarea
            className="small-textarea"
            onChange={(event) => onChange("constraints", event.target.value)}
            placeholder="Travel, location, timeline, role scope, sponsorship, compensation constraints"
            suppressHydrationWarning
            value={intent.constraints}
          />
        </label>
      </div>
    </section>
  );
}

function ChangeSummary({ turn }: { turn: MockIntakeTurn | null }) {
  if (!turn) {
    return (
      <div className="empty-state-block">
        <h3>No changes yet</h3>
        <p>Use the JobOps command center above to update your profile draft.</p>
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

export function DraftProfilePreview({ draft }: { draft: MockProfileDraft | null }) {
  const [activeTab, setActiveTab] = useState<ReviewTabId>("experience");

  if (!draft) {
    return (
      <ReviewTabbedList activeTab={activeTab} draft={null} onTabChange={setActiveTab} />
    );
  }

  return <ReviewTabbedList activeTab={activeTab} draft={draft} onTabChange={setActiveTab} />;
}

export function ReviewTabbedList({
  activeTab,
  draft,
  onTabChange
}: {
  activeTab: ReviewTabId;
  draft: MockProfileDraft | null;
  onTabChange: (tab: ReviewTabId) => void;
}) {
  const counts = buildReviewCounts(draft);
  const activeLabel = reviewTabs.find((tab) => tab.id === activeTab)?.label || "Profile data";

  return (
    <div className="profile-review-tabs">
      <div className="profile-review-tablist" role="tablist" aria-orientation="vertical" aria-label="Profile data types">
        {reviewTabs.map((tab) => (
          <button
            aria-controls={`profile-review-panel-${tab.id}`}
            aria-selected={activeTab === tab.id}
            className={`profile-review-tab${activeTab === tab.id ? " active" : ""}`}
            id={`profile-review-tab-${tab.id}`}
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            role="tab"
            suppressHydrationWarning
            type="button"
          >
            <span>{tab.label}</span>
            <strong>{counts[tab.id]}</strong>
          </button>
        ))}
      </div>
      <section
        aria-labelledby={`profile-review-tab-${activeTab}`}
        className="profile-review-panel"
        id={`profile-review-panel-${activeTab}`}
        role="tabpanel"
      >
        <div className="profile-review-panel-header">
          <h3>{activeLabel}</h3>
          <span>{counts[activeTab]}</span>
        </div>
        <div className="profile-compare-grid">
          <section className="profile-review-card" aria-label={`Current draft ${activeLabel}`}>
            <div className="profile-review-card-header">
              <h4>Current draft</h4>
              <span>{counts[activeTab]} draft</span>
            </div>
            <ProfileReviewTabContent activeTab={activeTab} draft={draft} />
          </section>
          <section className="profile-review-card published-profile-card" aria-label={`Current published profile ${activeLabel}`}>
            <div className="profile-review-card-header">
              <h4>Current published profile</h4>
              <span>0 published</span>
            </div>
            <EmptyMessage>No published {activeLabel.toLowerCase()} yet.</EmptyMessage>
          </section>
        </div>
      </section>
    </div>
  );
}

function ProfileReviewTabContent({ activeTab, draft }: { activeTab: ReviewTabId; draft: MockProfileDraft | null }) {
  if (!draft) {
    return <EmptyReviewList activeTab={activeTab} />;
  }

  if (activeTab === "experience") {
    const items = draft.experienceSummaries.filter((item) => {
      const itemType = getReviewItemType(item);
      return itemType === "experience" || itemType === "project";
    });
    return <ExperienceList emptyLabel="No experience or project items drafted yet." items={items} />;
  }

  if (activeTab === "education") {
    const educationFacts = draft.facts.filter((fact) => getFactCredentialType(fact) === "education");
    return (
      <CredentialList
        emptyLabel="No education items drafted yet."
        facts={educationFacts}
        items={draft.experienceSummaries.filter((item) => getReviewItemType(item) === "education")}
      />
    );
  }

  if (activeTab === "certifications") {
    const certificationFacts = draft.facts.filter((fact) => getFactCredentialType(fact) === "certification");
    return (
      <CredentialList
        emptyLabel="No certification items drafted yet."
        facts={certificationFacts}
        items={draft.experienceSummaries.filter((item) => getReviewItemType(item) === "certification")}
      />
    );
  }

  if (activeTab === "skills") {
    return draft.skillClaims.length ? (
      <ul className="profile-review-list">
        {draft.skillClaims.map((skill) => (
          <li className="profile-review-item profile-review-row" key={skill.id}>
            <div className="profile-review-primary">
              <strong>{skill.skill}</strong>
              <span>{skill.category}</span>
            </div>
            <CompactMeta
              items={[
                ["Years", formatYears(skill.yearsMin, skill.yearsMax)],
                ["Evidence", skill.evidence]
              ]}
            />
            <StatusBadges source={skill.source} />
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No skill claims drafted yet.</EmptyMessage>
    );
  }

  if (activeTab === "achievements") {
    const achievements = draft.facts.filter(
      (fact) => !getFactCredentialType(fact) && looksLikeAchievement(fact.claim, fact.category)
    );
    return achievements.length ? <FactList facts={achievements} /> : <EmptyMessage>No achievement or outcome items drafted yet.</EmptyMessage>;
  }

  if (activeTab === "facts") {
    const facts = draft.facts.filter((fact) => !getFactCredentialType(fact));
    return facts.length ? <FactList facts={facts} /> : <EmptyMessage>No facts or claims drafted yet.</EmptyMessage>;
  }

  return draft.links.length ? (
    <ul className="profile-review-list">
      {draft.links.map((link) => (
        <li className="profile-review-item profile-review-row" key={link.id}>
          <div className="profile-review-primary">
            <strong>{link.label}</strong>
            <a href={link.url} rel="noreferrer" target="_blank">
              {link.url}
            </a>
          </div>
          <StatusBadges source={link.source} />
        </li>
      ))}
    </ul>
  ) : (
    <EmptyMessage>No evidence links drafted yet.</EmptyMessage>
  );
}

function ExperienceList({ emptyLabel, items }: { emptyLabel: string; items: MockProfileDraft["experienceSummaries"] }) {
  if (!items.length) {
    return <EmptyMessage>{emptyLabel}</EmptyMessage>;
  }

  return (
    <ul className="profile-review-list">
      {items.map((experience) => (
        <li className="profile-review-item" key={experience.id}>
          <div className="profile-review-primary">
            <strong>{experience.title}</strong>
            <span>{experience.organization}</span>
          </div>
          <DetailGrid
            items={[
              ["Dates", formatDateRange(experience.startDate, experience.endDate)],
              ["Location", experience.location],
              ["Type", getReviewItemType(experience)]
            ]}
          />
          <p>{experience.summary}</p>
          {experience.bullets.length ? (
            <ul className="profile-review-bullets">
              {experience.bullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          ) : null}
          <StatusBadges source={experience.source} />
        </li>
      ))}
    </ul>
  );
}

function CredentialList({
  emptyLabel,
  facts,
  items
}: {
  emptyLabel: string;
  facts: MockProfileDraft["facts"];
  items: MockProfileDraft["experienceSummaries"];
}) {
  if (!items.length && !facts.length) {
    return <EmptyMessage>{emptyLabel}</EmptyMessage>;
  }

  return (
    <ul className="profile-review-list">
      {items.map((experience) => (
        <li className="profile-review-item" key={experience.id}>
          <div className="profile-review-primary">
            <strong>{experience.title}</strong>
            <span>{experience.organization}</span>
          </div>
          <DetailGrid
            items={[
              ["Dates", formatDateRange(experience.startDate, experience.endDate)],
              ["Location", experience.location],
              ["Type", getReviewItemType(experience)]
            ]}
          />
          <p>{experience.summary}</p>
          {experience.bullets.length ? (
            <ul className="profile-review-bullets">
              {experience.bullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          ) : null}
          <StatusBadges source={experience.source} />
        </li>
      ))}
      {facts.map((fact) => (
        <li className="profile-review-item profile-review-row" key={fact.id}>
          <div className="profile-review-primary">
            <strong>{fact.claim}</strong>
            <span>{fact.category}</span>
          </div>
          <StatusBadges source={fact.source} />
        </li>
      ))}
    </ul>
  );
}

function FactList({ facts }: { facts: MockProfileDraft["facts"] }) {
  return (
    <ul className="profile-review-list">
      {facts.map((fact) => (
        <li className="profile-review-item profile-review-row" key={fact.id}>
          <div className="profile-review-primary">
            <strong>{fact.category}</strong>
            <span>{fact.claim}</span>
          </div>
          <StatusBadges source={fact.source} />
        </li>
      ))}
    </ul>
  );
}

function DetailGrid({ items }: { items: Array<[string, string]> }) {
  const visibleItems = items.filter(([, value]) => value.trim().length > 0);
  if (!visibleItems.length) {
    return null;
  }

  return (
    <dl className="profile-review-details">
      {visibleItems.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function CompactMeta({ items }: { items: Array<[string, string]> }) {
  const visibleItems = items.filter(([, value]) => value.trim().length > 0);
  if (!visibleItems.length) {
    return null;
  }

  return (
    <dl className="profile-review-meta">
      {visibleItems.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function EmptyReviewList({ activeTab }: { activeTab: ReviewTabId }) {
  const label = reviewTabs.find((tab) => tab.id === activeTab)?.label.toLowerCase() || "items";
  return <EmptyMessage>No {label} drafted yet.</EmptyMessage>;
}

function EmptyMessage({ children }: { children: React.ReactNode }) {
  return <p className="profile-review-empty">{children}</p>;
}

function buildReviewCounts(draft: MockProfileDraft | null): Record<ReviewTabId, number> {
  return {
    experience:
      draft?.experienceSummaries.filter((item) => {
        const itemType = getReviewItemType(item);
        return itemType === "experience" || itemType === "project";
      }).length ?? 0,
    skills: draft?.skillClaims.length ?? 0,
    achievements:
      draft?.facts.filter((fact) => !getFactCredentialType(fact) && looksLikeAchievement(fact.claim, fact.category))
        .length ?? 0,
    facts: draft?.facts.filter((fact) => !getFactCredentialType(fact)).length ?? 0,
    evidence: draft?.links.length ?? 0,
    education:
      (draft?.experienceSummaries.filter((item) => getReviewItemType(item) === "education").length ?? 0) +
      (draft?.facts.filter((fact) => getFactCredentialType(fact) === "education").length ?? 0),
    certifications:
      (draft?.experienceSummaries.filter((item) => getReviewItemType(item) === "certification").length ?? 0) +
      (draft?.facts.filter((fact) => getFactCredentialType(fact) === "certification").length ?? 0)
  };
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

function getReviewItemType(item: MockProfileDraft["experienceSummaries"][number]) {
  if (item.itemType === "education" || item.itemType === "certification") {
    return item.itemType;
  }

  const normalized = `${item.title} ${item.organization} ${item.summary} ${item.bullets.join(" ")}`.toLowerCase();
  if (/certificate|certification|coursera|credential/.test(normalized)) {
    return "certification";
  }
  if (/university|college|b\.a\.|b\.s\.|degree|stanford|bachelor|master/.test(normalized)) {
    return "education";
  }
  return item.itemType;
}

function getFactCredentialType(fact: MockProfileDraft["facts"][number]) {
  const normalized = `${fact.category} ${fact.claim}`.toLowerCase();
  if (/certificate|certification|credential|coursera/.test(normalized)) {
    return "certification";
  }
  if (/education|university|college|b\.a\.|b\.s\.|degree|bachelor|master/.test(normalized)) {
    return "education";
  }
  return "";
}

function formatYears(yearsMin?: number, yearsMax?: number) {
  if (typeof yearsMin === "number" && typeof yearsMax === "number" && yearsMin !== yearsMax) {
    return `${yearsMin}-${yearsMax} years`;
  }
  if (typeof yearsMin === "number") {
    return `${yearsMin}+ years`;
  }
  if (typeof yearsMax === "number") {
    return `Up to ${yearsMax} years`;
  }
  return "";
}

function formatDateRange(startDate: string, endDate: string) {
  if (startDate && endDate) {
    return `${startDate} - ${endDate}`;
  }
  return startDate || endDate;
}

function looksLikeAchievement(claim: string, category: string) {
  const normalized = `${claim} ${category}`.toLowerCase();
  return /%|\d|reduced|improved|increased|launched|shipped|built|deployed|optimized|scaled|throughput|hours|minutes/.test(
    normalized
  );
}
