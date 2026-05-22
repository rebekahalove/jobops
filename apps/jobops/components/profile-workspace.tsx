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

type ProfileSummary = {
  displayName: string;
  headline: string;
  summary: string;
  profileStatus: "draft" | "published";
  tenantSlug?: string;
};

type ProfileWorkspacePayload = {
  profile?: ProfileSummary;
  draft: ProfileIntakeOutput & { statusSummary?: string };
  publicProfile?: PublicProfileSnapshot;
  publicPortfolioPath?: string;
  publishedPublicItemCount?: number;
};

type PublicProfileSnapshot = {
  displayName?: string;
  headline?: string;
  summary?: string;
  profileStatus?: "draft" | "published";
  facts?: Array<{
    id: string;
    claim: string;
    category: string;
    source: string;
    visibility: "private" | "public";
    verificationStatus: string;
  }>;
  skillClaims?: Array<{
    id: string;
    skill: string;
    category: string;
    evidence?: string | null;
    visibility: "private" | "public";
    verificationStatus: string;
    publicationStatus: string;
  }>;
  experienceAndProjects?: Array<{
    id: string;
    itemType?: "experience" | "project" | "education" | "certification";
    title: string;
    organization?: string | null;
    startDate?: string | null;
    endDate?: string | null;
    location?: string | null;
    summary: string;
    bullets?: string[];
    visibility: "private" | "public";
    publicationStatus: string;
  }>;
  evidenceLinks?: Array<{
    id: string;
    label: string;
    url: string;
    visibility: "private" | "public";
    publicationStatus: string;
  }>;
};

type DraftItemPatch = {
  claim?: string;
  category?: string;
  skill?: string;
  evidence?: string;
  title?: string;
  organization?: string;
  summary?: string;
  url?: string;
  label?: string;
  visibility?: "private" | "public";
  reviewStatus?: MockProfileDraft["facts"][number]["status"];
};

export function ProfileWorkspace({ apiBasePath = "/api" }: { apiBasePath?: string }) {
  const [intent, setIntent] = useState<TargetRoleIntent>(emptyTargetRoleIntent);
  const [draft, setDraft] = useState<MockProfileDraft | null>(null);
  const [profile, setProfile] = useState<ProfileSummary | null>(null);
  const [publicProfile, setPublicProfile] = useState<PublicProfileSnapshot | null>(null);
  const [publicPortfolioPath, setPublicPortfolioPath] = useState<string | null>(null);
  const [publishedPublicItemCount, setPublishedPublicItemCount] = useState(0);
  const [lastTurn, setLastTurn] = useState<MockIntakeTurn | null>(null);
  const [editedFields, setEditedFields] = useState<Set<IntentField>>(() => new Set());
  const [workspaceMessage, setWorkspaceMessage] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isChangeExpanded, setIsChangeExpanded] = useState(true);
  const [isReviewExpanded, setIsReviewExpanded] = useState(true);
  const [isQuestionsExpanded, setIsQuestionsExpanded] = useState(true);

  async function loadProfileState(options: { cancelled?: () => boolean } = {}) {
    try {
      const response = await fetch(`${apiBasePath}/profile`);
      const payload = (await response.json()) as
        | { ok: true; result: ProfileWorkspacePayload }
        | { ok: false; error: string };

      if (options.cancelled?.()) {
        return;
      }

      if (!response.ok || !payload.ok) {
        return;
      }

      applyProfilePayload(payload.result);
    } catch {
      return;
    }
  }

  function applyProfilePayload(result: ProfileWorkspacePayload) {
    const nextState = applyProfileIntakeOutputToState(emptyTargetRoleIntent, result.draft);
    setIntent(nextState.intent);
    setDraft(nextState.draft);
    setLastTurn(nextState.turn);
    setProfile(result.profile ?? null);
    setPublicProfile(result.publicProfile ?? null);
    setPublicPortfolioPath(result.publicPortfolioPath ?? null);
    setPublishedPublicItemCount(result.publishedPublicItemCount ?? 0);
  }

  useEffect(() => {
    let cancelled = false;

    function refreshLatestDraft() {
      void loadProfileState({ cancelled: () => cancelled });
    }

    void loadProfileState({ cancelled: () => cancelled });
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

  async function updateProfileFields(patch: { displayName?: string; headline?: string; summary?: string }) {
    const response = await fetch(`${apiBasePath}/profile`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(patch)
    });
    const payload = (await response.json()) as { ok: true; result: ProfileWorkspacePayload } | { ok: false; error: string };
    if (!response.ok || !payload.ok) {
      setWorkspaceMessage(payload.ok === false ? payload.error : "Profile update failed.");
      return;
    }
    applyProfilePayload(payload.result);
    setWorkspaceMessage("Profile basics saved.");
  }

  async function updateDraftItem(itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) {
    const response = await fetch(`${apiBasePath}/profile/draft-items/${itemType}/${itemId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(patch)
    });
    const payload = (await response.json()) as { ok: true; result: ProfileWorkspacePayload } | { ok: false; error: string };
    if (!response.ok || !payload.ok) {
      setWorkspaceMessage(payload.ok === false ? payload.error : "Draft item update failed.");
      return;
    }
    applyProfilePayload(payload.result);
    setWorkspaceMessage("Draft item updated.");
  }

  async function publishApprovedPublicFacts() {
    setIsPublishing(true);
    setWorkspaceMessage(null);
    try {
      const response = await fetch(`${apiBasePath}/profile`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ action: "publish" })
      });
      const payload = (await response.json()) as
        | { ok: true; result: ProfileWorkspacePayload; publishedCount?: number }
        | { ok: false; error: string };
      if (!response.ok || !payload.ok) {
        setWorkspaceMessage(payload.ok === false ? payload.error : "Profile publish failed.");
        return;
      }
      applyProfilePayload(payload.result);
      setWorkspaceMessage(`Published ${payload.publishedCount ?? 0} approved public item(s).`);
    } catch {
      setWorkspaceMessage("Profile publish API is unavailable. Start the FastAPI service and try again.");
    } finally {
      setIsPublishing(false);
    }
  }

  return (
    <main className="dashboard-main profile-workspace">
      <CollapsiblePanel
        aside={
          <ProfileStatusIcons />
        }
        className="review-shell"
        eyebrow="Structured review"
        expanded={isReviewExpanded}
        id="review-title"
        onToggle={() => setIsReviewExpanded((current) => !current)}
        subtitle="Use the JobOps command center above to update your profile. This workspace shows the saved draft profile state for review, correction, and later verification."
        title="Review your JobOps profile draft."
      >
        <div className="publish-toolbar">
          <p>
            {publishedPublicItemCount > 0
              ? `Published profile has ${publishedPublicItemCount} public item(s).`
              : "Approve items, mark only appropriate material public, then publish approved public facts."}
          </p>
          {publicPortfolioPath && publishedPublicItemCount > 0 ? (
            <a className="secondary-action" href={publicPortfolioPath}>
              View public portfolio
            </a>
          ) : null}
          <button className="secondary-action button-action" disabled={isPublishing} onClick={publishApprovedPublicFacts} type="button">
            {isPublishing ? "Publishing..." : "Publish approved public facts"}
          </button>
        </div>
        <details className="profile-basics-details">
          <summary>Profile basics</summary>
          <ProfileBasicsPanel onSave={updateProfileFields} profile={profile} />
        </details>
        {workspaceMessage ? <p className="profile-workspace-message">{workspaceMessage}</p> : null}
        <section className="review-subsection" aria-labelledby="current-draft-title">
          <div>
            <h3 id="current-draft-title">Current Draft</h3>
          </div>
          <div className="current-draft-stack">
            <TargetsCard editedFields={editedFields} intent={intent} onChange={updateIntent} />
            <DraftProfilePreview draft={draft} onDraftItemUpdate={updateDraftItem} publicProfile={publicProfile} />
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
  value
}: {
  editedFields: Set<IntentField>;
  field: IntentField;
  label: string;
  onChange: (field: IntentField, value: string) => void;
  value: string;
}) {
  return (
    <label>
      <FieldLabel edited={editedFields.has(field)} label={label} />
      <input
        onChange={(event) => onChange(field, event.target.value)}
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
      <DraftIconSet author={edited ? "user" : "agent"} status="needs_review" visibility="private" />
    </span>
  );
}

function ProfileStatusIcons() {
  return (
    <span className="profile-status-bar icon-badge-row" aria-label="Profile-level statuses">
      <IconBadge kind="review" label="Needs verification" />
      <IconBadge kind="private" label="Private" />
      <IconBadge kind="unpublished" label="Not published" />
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
          value={intent.targetTitles}
        />
        <IntentFieldControl
          editedFields={editedFields}
          field="roleFamilies"
          label="Target role families"
          onChange={onChange}
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
          value={intent.preferredLocations}
        />
        <IntentFieldControl
          editedFields={editedFields}
          field="domainsOfInterest"
          label="Domains or industries of interest"
          onChange={onChange}
          value={intent.domainsOfInterest}
        />
        <label>
          <FieldLabel edited={editedFields.has("constraints")} label="Dealbreakers or constraints" />
          <textarea
            className="small-textarea"
            onChange={(event) => onChange("constraints", event.target.value)}
            suppressHydrationWarning
            value={intent.constraints}
          />
        </label>
      </div>
    </section>
  );
}

function ProfileBasicsPanel({
  onSave,
  profile
}: {
  onSave: (patch: { displayName?: string; headline?: string; summary?: string }) => void;
  profile: ProfileSummary | null;
}) {
  const [displayName, setDisplayName] = useState(profile?.displayName ?? "");
  const [headline, setHeadline] = useState(profile?.headline ?? "");
  const [summary, setSummary] = useState(profile?.summary ?? "");

  useEffect(() => {
    setDisplayName(profile?.displayName ?? "");
    setHeadline(profile?.headline ?? "");
    setSummary(profile?.summary ?? "");
  }, [profile]);

  return (
    <section className="profile-basics-panel" aria-labelledby="profile-basics-title">
      <div>
        <p className="eyebrow">Profile basics</p>
        <h2 id="profile-basics-title">Public profile shell</h2>
        <p>These fields can appear on the public portfolio once you publish approved public content.</p>
      </div>
      <div className="profile-basics-form">
        <label>
          <span>Display name</span>
          <input onChange={(event) => setDisplayName(event.target.value)} value={displayName} />
        </label>
        <label>
          <span>Headline</span>
          <input onChange={(event) => setHeadline(event.target.value)} value={headline} />
        </label>
        <label className="full-span">
          <span>Summary</span>
          <textarea onChange={(event) => setSummary(event.target.value)} value={summary} />
        </label>
        <button
          className="secondary-action button-action"
          onClick={() => onSave({ displayName, headline, summary })}
          type="button"
        >
          Save profile basics
        </button>
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

export function DraftProfilePreview({
  draft,
  onDraftItemUpdate,
  publicProfile
}: {
  draft: MockProfileDraft | null;
  onDraftItemUpdate?: (itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) => void;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const [activeTab, setActiveTab] = useState<ReviewTabId>("experience");

  if (!draft) {
    return (
      <ReviewTabbedList activeTab={activeTab} draft={null} onDraftItemUpdate={onDraftItemUpdate} onTabChange={setActiveTab} publicProfile={publicProfile} />
    );
  }

  return <ReviewTabbedList activeTab={activeTab} draft={draft} onDraftItemUpdate={onDraftItemUpdate} onTabChange={setActiveTab} publicProfile={publicProfile} />;
}

export function ReviewTabbedList({
  activeTab,
  draft,
  onDraftItemUpdate,
  onTabChange,
  publicProfile
}: {
  activeTab: ReviewTabId;
  draft: MockProfileDraft | null;
  onDraftItemUpdate?: (itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) => void;
  onTabChange: (tab: ReviewTabId) => void;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const counts = buildReviewCounts(draft);
  const publicCounts = buildPublicReviewCounts(publicProfile);
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
            <ProfileReviewTabContent activeTab={activeTab} draft={draft} onDraftItemUpdate={onDraftItemUpdate} />
          </section>
          <section className="profile-review-card published-profile-card" aria-label={`Current published profile ${activeLabel}`}>
            <div className="profile-review-card-header">
              <h4>Current published profile</h4>
              <span>{publicCounts[activeTab]} published</span>
            </div>
            <PublishedProfileTabContent activeTab={activeTab} publicProfile={publicProfile} />
          </section>
        </div>
      </section>
    </div>
  );
}

function ProfileReviewTabContent({
  activeTab,
  draft,
  onDraftItemUpdate
}: {
  activeTab: ReviewTabId;
  draft: MockProfileDraft | null;
  onDraftItemUpdate?: (itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) => void;
}) {
  if (!draft) {
    return <EmptyReviewList activeTab={activeTab} />;
  }

  if (activeTab === "experience") {
    const items = draft.experienceSummaries.filter((item) => item.itemType === "experience" || item.itemType === "project");
    return <ExperienceList emptyLabel="No experience or project items drafted yet." items={items} onDraftItemUpdate={onDraftItemUpdate} showType />;
  }

  if (activeTab === "education") {
    return (
      <ExperienceList
        emptyLabel="No education items drafted yet."
        items={draft.experienceSummaries.filter((item) => item.itemType === "education")}
        onDraftItemUpdate={onDraftItemUpdate}
      />
    );
  }

  if (activeTab === "certifications") {
    return (
      <ExperienceList
        emptyLabel="No certification items drafted yet."
        items={draft.experienceSummaries.filter((item) => item.itemType === "certification")}
        onDraftItemUpdate={onDraftItemUpdate}
      />
    );
  }

  if (activeTab === "skills") {
    return draft.skillClaims.length ? (
      <ul className="profile-review-list">
        {draft.skillClaims.map((skill) => (
          <li className="profile-review-item profile-review-row" key={skill.id}>
            <div className="profile-review-primary">
              <TitleWithBadges title={skill.skill}>
                <ItemIconSet item={skill} />
              </TitleWithBadges>
              <span>{skill.category}</span>
            </div>
            <CompactMeta
              items={[
                ["Years", formatYears(skill.yearsMin, skill.yearsMax)],
                ["Evidence", skill.evidence]
              ]}
            />
            <ReviewActions
              item={skill}
              itemType="skill"
              onDraftItemUpdate={onDraftItemUpdate}
            />
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No skill claims drafted yet.</EmptyMessage>
    );
  }

  if (activeTab === "achievements") {
    const achievements = draft.facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category));
    return achievements.length ? <FactList facts={achievements} onDraftItemUpdate={onDraftItemUpdate} /> : <EmptyMessage>No achievement or outcome items drafted yet.</EmptyMessage>;
  }

  if (activeTab === "facts") {
    return draft.facts.length ? <FactList facts={draft.facts} onDraftItemUpdate={onDraftItemUpdate} /> : <EmptyMessage>No facts or claims drafted yet.</EmptyMessage>;
  }

  return draft.links.length ? (
    <ul className="profile-review-list">
      {draft.links.map((link) => (
        <li className="profile-review-item profile-review-row" key={link.id}>
          <div className="profile-review-primary">
            <TitleWithBadges title={link.label}>
              <ItemIconSet item={link} />
            </TitleWithBadges>
            <a href={link.url} rel="noreferrer" target="_blank">
              {link.url}
            </a>
          </div>
          <ReviewActions item={link} itemType="evidence" onDraftItemUpdate={onDraftItemUpdate} />
        </li>
      ))}
    </ul>
  ) : (
    <EmptyMessage>No evidence links drafted yet.</EmptyMessage>
  );
}

function ExperienceList({
  emptyLabel,
  items,
  onDraftItemUpdate,
  showType = false
}: {
  emptyLabel: string;
  items: MockProfileDraft["experienceSummaries"];
  onDraftItemUpdate?: (itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) => void;
  showType?: boolean;
}) {
  if (!items.length) {
    return <EmptyMessage>{emptyLabel}</EmptyMessage>;
  }

  return (
    <ul className="profile-review-list">
      {items.map((experience) => (
        <li className="profile-review-item" key={experience.id}>
          <div className="profile-review-primary">
            <TitleWithBadges title={experience.title}>
              <ItemIconSet item={experience} />
            </TitleWithBadges>
            <span>{experience.organization}</span>
          </div>
          <DetailGrid
            items={buildExperienceDetails(experience, showType)}
          />
          <p>{experience.summary}</p>
          {experience.bullets.length ? (
            <ul className="profile-review-bullets">
              {experience.bullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          ) : null}
          {showType ? <p className="profile-item-type">Type: {experience.itemType}</p> : null}
          <ReviewActions item={experience} itemType="experience" onDraftItemUpdate={onDraftItemUpdate} />
        </li>
      ))}
    </ul>
  );
}

function FactList({
  facts,
  onDraftItemUpdate
}: {
  facts: MockProfileDraft["facts"];
  onDraftItemUpdate?: (itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) => void;
}) {
  return (
    <ul className="profile-review-list">
      {facts.map((fact) => (
        <EditableFactRow fact={fact} key={fact.id} onDraftItemUpdate={onDraftItemUpdate} />
      ))}
    </ul>
  );
}

function PublishedProfileTabContent({
  activeTab,
  publicProfile
}: {
  activeTab: ReviewTabId;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  if (!publicProfile) {
    return <EmptyMessage>No published profile loaded yet.</EmptyMessage>;
  }

  if (activeTab === "skills") {
    const skills = publicProfile.skillClaims ?? [];
    return skills.length ? (
      <ul className="profile-review-list">
        {skills.map((skill) => (
          <li className="profile-review-item" key={skill.id}>
            <strong>{skill.skill}</strong>
            <span>{skill.category}</span>
            {skill.evidence ? <p>{skill.evidence}</p> : null}
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No published skills yet.</EmptyMessage>
    );
  }

  if (activeTab === "experience" || activeTab === "education" || activeTab === "certifications") {
    const itemTypes =
      activeTab === "experience" ? ["experience", "project"] : activeTab === "education" ? ["education"] : ["certification"];
    const items = (publicProfile.experienceAndProjects ?? []).filter((item) => itemTypes.includes(item.itemType || "experience"));
    return items.length ? (
      <ul className="profile-review-list">
        {items.map((item) => (
          <li className="profile-review-item" key={item.id}>
            <strong>{item.title}</strong>
            {item.organization ? <span>{item.organization}</span> : null}
            <p>{item.summary}</p>
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No published {reviewTabs.find((tab) => tab.id === activeTab)?.label.toLowerCase()} yet.</EmptyMessage>
    );
  }

  if (activeTab === "evidence") {
    const links = publicProfile.evidenceLinks ?? [];
    return links.length ? (
      <ul className="profile-review-list">
        {links.map((link) => (
          <li className="profile-review-item" key={link.id}>
            <strong>{link.label}</strong>
            <a href={link.url} rel="noreferrer" target="_blank">
              {link.url}
            </a>
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No published evidence links yet.</EmptyMessage>
    );
  }

  const facts = (publicProfile.facts ?? []).filter((fact) =>
    activeTab === "achievements" ? looksLikeAchievement(fact.claim, fact.category) : true
  );
  return facts.length ? (
    <ul className="profile-review-list">
      {facts.map((fact) => (
        <li className="profile-review-item" key={fact.id}>
          <strong>{fact.category}</strong>
          <span>{fact.claim}</span>
        </li>
      ))}
    </ul>
  ) : (
    <EmptyMessage>No published {activeTab === "achievements" ? "achievements" : "facts"} yet.</EmptyMessage>
  );
}

function EditableFactRow({
  fact,
  onDraftItemUpdate
}: {
  fact: MockProfileDraft["facts"][number];
  onDraftItemUpdate?: (itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) => void;
}) {
  const [claim, setClaim] = useState(fact.claim);
  const [category, setCategory] = useState(fact.category);

  useEffect(() => {
    setClaim(fact.claim);
    setCategory(fact.category);
  }, [fact]);

  return (
    <li className="profile-review-item fact-edit-row">
      <div className="profile-review-primary">
        <TitleWithBadges title={fact.category}>
          <ItemIconSet item={fact} />
        </TitleWithBadges>
      </div>
      <label>
        <span>Claim</span>
        <textarea className="small-textarea" onChange={(event) => setClaim(event.target.value)} value={claim} />
      </label>
      <label>
        <span>Category</span>
        <input onChange={(event) => setCategory(event.target.value)} value={category} />
      </label>
      <div className="review-action-row">
        <button
          className="secondary-action button-action"
          disabled={!onDraftItemUpdate}
          onClick={() => onDraftItemUpdate?.("fact", fact.id, { claim, category })}
          type="button"
        >
          Save fact
        </button>
        <ReviewActions item={fact} itemType="fact" onDraftItemUpdate={onDraftItemUpdate} />
      </div>
    </li>
  );
}

function ReviewActions({
  item,
  itemType,
  onDraftItemUpdate
}: {
  item: BadgeableDraftItem & { id: string };
  itemType: "fact" | "skill" | "experience" | "evidence";
  onDraftItemUpdate?: (itemType: "fact" | "skill" | "experience" | "evidence", itemId: string, patch: DraftItemPatch) => void;
}) {
  return (
    <div className="review-action-row">
      <select
        aria-label="Visibility"
        disabled={!onDraftItemUpdate || item.published}
        onChange={(event) => onDraftItemUpdate?.(itemType, item.id, { visibility: event.target.value as "private" | "public" })}
        value={item.visibility}
      >
        <option value="private">Private</option>
        <option value="public">Public</option>
      </select>
      <button
        className="secondary-action button-action"
        disabled={!onDraftItemUpdate || item.published}
        onClick={() => onDraftItemUpdate?.(itemType, item.id, { reviewStatus: "candidate_approved" })}
        type="button"
      >
        Approve
      </button>
      <button
        className="secondary-action button-action subtle-danger"
        disabled={!onDraftItemUpdate || item.published}
        onClick={() => onDraftItemUpdate?.(itemType, item.id, { reviewStatus: "rejected", visibility: "private" })}
        type="button"
      >
        Reject
      </button>
    </div>
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
      draft?.experienceSummaries.filter((item) => item.itemType === "experience" || item.itemType === "project")
        .length ?? 0,
    skills: draft?.skillClaims.length ?? 0,
    achievements: draft?.facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category)).length ?? 0,
    facts: draft?.facts.length ?? 0,
    evidence: draft?.links.length ?? 0,
    education: draft?.experienceSummaries.filter((item) => item.itemType === "education").length ?? 0,
    certifications: draft?.experienceSummaries.filter((item) => item.itemType === "certification").length ?? 0
  };
}

function buildPublicReviewCounts(publicProfile?: PublicProfileSnapshot | null): Record<ReviewTabId, number> {
  const facts = publicProfile?.facts ?? [];
  const experience = publicProfile?.experienceAndProjects ?? [];
  return {
    experience: experience.filter((item) => (item.itemType || "experience") === "experience" || item.itemType === "project").length,
    skills: publicProfile?.skillClaims?.length ?? 0,
    achievements: facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category)).length,
    facts: facts.length,
    evidence: publicProfile?.evidenceLinks?.length ?? 0,
    education: experience.filter((item) => item.itemType === "education").length,
    certifications: experience.filter((item) => item.itemType === "certification").length
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

type IconBadgeKind =
  | "review"
  | "private"
  | "public"
  | "published"
  | "unpublished"
  | "resume"
  | "chat"
  | "model"
  | "agent"
  | "user";

type BadgeableDraftItem = {
  source: MockProfileDraft["facts"][number]["source"];
  status: MockProfileDraft["facts"][number]["status"];
  visibility: "private" | "public";
  published: boolean;
};

function TitleWithBadges({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <span className="profile-title-line">
      <strong>{title}</strong>
      {children}
    </span>
  );
}

function ItemIconSet({ item }: { item: BadgeableDraftItem }) {
  return (
    <span className="icon-badge-row">
      <ReviewIcon status={item.status} />
      <VisibilityIcon visibility={item.visibility} />
      <PublicationIcon published={item.published} />
      <SourceIcon source={item.source} />
    </span>
  );
}

function DraftIconSet({
  author,
  status,
  visibility
}: {
  author: "agent" | "user";
  status: BadgeableDraftItem["status"];
  visibility: BadgeableDraftItem["visibility"];
}) {
  return (
    <span className="icon-badge-row">
      <AuthorIcon author={author} />
      <ReviewIcon status={status} />
      <VisibilityIcon visibility={visibility} />
    </span>
  );
}

function ReviewIcon({ status }: { status: BadgeableDraftItem["status"] }) {
  if (status !== "needs_review" && status !== "draft") {
    return null;
  }

  return <IconBadge kind="review" label={status === "draft" ? "Draft" : "Needs review"} />;
}

function VisibilityIcon({ visibility }: { visibility: BadgeableDraftItem["visibility"] }) {
  return <IconBadge kind={visibility === "private" ? "private" : "public"} label={visibilityLabel(visibility)} />;
}

function PublicationIcon({ published }: { published: BadgeableDraftItem["published"] }) {
  return <IconBadge kind={published ? "published" : "unpublished"} label={published ? "Published" : "Not published"} />;
}

function SourceIcon({ source }: { source: BadgeableDraftItem["source"] }) {
  return <IconBadge kind={source} label={sourceLabel(source)} />;
}

function AuthorIcon({ author }: { author: "agent" | "user" }) {
  return <IconBadge kind={author} label={author === "user" ? "Edited by you" : "Agent draft"} />;
}

function IconBadge({ kind, label }: { kind: IconBadgeKind; label: string }) {
  return (
    <span aria-label={label} className={`icon-badge ${kind}`} role="img" title={label}>
      <IconGlyph kind={kind} />
    </span>
  );
}

function IconGlyph({ kind }: { kind: IconBadgeKind }) {
  if (kind === "review") {
    return <span className="review-dot" aria-hidden="true" />;
  }

  if (kind === "resume") {
    return (
      <span className="cv-icon" aria-hidden="true">
        CV
      </span>
    );
  }

  if (kind === "private") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M3 3l18 18" />
        <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
        <path d="M9.5 5.3A9.8 9.8 0 0 1 12 5c5 0 8.5 4.5 9 7a9.9 9.9 0 0 1-2 3.4" />
        <path d="M6.6 6.7C4.7 8 3.4 10.1 3 12c.5 2.5 4 7 9 7 1.4 0 2.7-.3 3.8-.9" />
      </svg>
    );
  }

  if (kind === "public") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M3 12c.5-2.5 4-7 9-7s8.5 4.5 9 7c-.5 2.5-4 7-9 7s-8.5-4.5-9-7z" />
        <circle cx="12" cy="12" r="2.5" />
      </svg>
    );
  }

  if (kind === "published") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M5 13l4 4L19 7" />
      </svg>
    );
  }

  if (kind === "unpublished") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8" />
        <path d="M8 12h8" />
      </svg>
    );
  }

  if (kind === "chat" || kind === "user") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <circle cx="12" cy="8" r="3" />
        <path d="M5.5 20c.8-3.8 3-6 6.5-6s5.7 2.2 6.5 6" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <rect x="6" y="8" width="12" height="9" rx="3" />
      <path d="M12 8V5" />
      <path d="M9.5 5h5" />
      <circle cx="10" cy="12" r=".7" />
      <circle cx="14" cy="12" r=".7" />
      <path d="M10 15h4" />
    </svg>
  );
}

function sourceLabel(source: MockProfileDraft["facts"][number]["source"]) {
  return source === "resume" ? "Source: Resume" : source === "model" ? "Source: Model" : "Source: Chat";
}

function visibilityLabel(visibility: BadgeableDraftItem["visibility"]) {
  return visibility === "private" ? "Private" : "Public";
}

function buildExperienceDetails(experience: MockProfileDraft["experienceSummaries"][number], showType: boolean) {
  const missingValue = showType ? "Needs review" : "";
  const details: Array<[string, string]> = [
    ["From", experience.startDate || missingValue],
    ["To", experience.endDate || missingValue],
    ["Location", experience.location || missingValue]
  ];

  return details;
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

function looksLikeAchievement(claim: string, category: string) {
  const normalized = `${claim} ${category}`.toLowerCase();
  return /%|\d|reduced|improved|increased|launched|shipped|built|deployed|optimized|scaled|throughput|hours|minutes/.test(
    normalized
  );
}
