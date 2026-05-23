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
  | "basics"
  | "targets"
  | "experience"
  | "skills"
  | "achievements"
  | "facts"
  | "evidence"
  | "education"
  | "certifications";

type LifecycleTab = "drafts" | "published";

const reviewTabs: Array<{ id: ReviewTabId; label: string }> = [
  { id: "basics", label: "Profile basics" },
  { id: "targets", label: "Targets" },
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
  publishedProfile?: PublishedProfileSnapshot;
  publicProfile?: PublicProfileSnapshot;
  publicPortfolioPath?: string;
  publishedItemCount?: number;
  publishedPublicItemCount?: number;
  archivedItemCount?: number;
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
  targetRoleIntent?: {
    id?: string;
    targetTitles?: string[];
    roleFamilies?: string[];
    preferredLocations?: string[];
    workModes?: string[];
    domainsOrIndustries?: string;
    visibility?: "private" | "public";
    publicationStatus?: string;
  };
};

type PublishedProfileSnapshot = PublicProfileSnapshot;

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
  publishVisibility?: "private" | "public";
};

type ProfileItemType = "fact" | "skill" | "experience" | "evidence" | "target-role";

type PublishedItemPatch = {
  visibility?: "private" | "public";
  archive?: boolean;
};

export function ProfileWorkspace({ apiBasePath = "/api" }: { apiBasePath?: string }) {
  const [intent, setIntent] = useState<TargetRoleIntent>(emptyTargetRoleIntent);
  const [draft, setDraft] = useState<MockProfileDraft | null>(null);
  const [profile, setProfile] = useState<ProfileSummary | null>(null);
  const [publishedProfile, setPublishedProfile] = useState<PublishedProfileSnapshot | null>(null);
  const [publicProfile, setPublicProfile] = useState<PublicProfileSnapshot | null>(null);
  const [publicPortfolioPath, setPublicPortfolioPath] = useState<string | null>(null);
  const [publishedItemCount, setPublishedItemCount] = useState(0);
  const [publishedPublicItemCount, setPublishedPublicItemCount] = useState(0);
  const [archivedItemCount, setArchivedItemCount] = useState(0);
  const [lastTurn, setLastTurn] = useState<MockIntakeTurn | null>(null);
  const [editedFields, setEditedFields] = useState<Set<IntentField>>(() => new Set());
  const [workspaceMessage, setWorkspaceMessage] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<ReviewTabId>("basics");
  const [activeLifecycle, setActiveLifecycle] = useState<LifecycleTab>("drafts");

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
    setPublishedProfile(result.publishedProfile ?? null);
    setPublicProfile(result.publicProfile ?? null);
    setPublicPortfolioPath(result.publicPortfolioPath ?? null);
    setPublishedItemCount(result.publishedItemCount ?? 0);
    setPublishedPublicItemCount(result.publishedPublicItemCount ?? 0);
    setArchivedItemCount(result.archivedItemCount ?? 0);
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

  async function updateDraftItem(itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) {
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
    setWorkspaceMessage(buildDraftActionMessage(patch));
  }

  async function updatePublishedItem(itemType: ProfileItemType, itemId: string, patch: PublishedItemPatch) {
    const response = await fetch(`${apiBasePath}/profile/published-items/${itemType}/${itemId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(patch)
    });
    const payload = (await response.json()) as { ok: true; result: ProfileWorkspacePayload } | { ok: false; error: string };
    if (!response.ok || !payload.ok) {
      setWorkspaceMessage(payload.ok === false ? payload.error : "Published item update failed.");
      return;
    }
    applyProfilePayload(payload.result);
    setWorkspaceMessage(patch.archive ? "Published item archived." : "Published item visibility updated.");
  }

  const draftItemCount = totalDraftCount(draft);
  const internalPublishedCount = Math.max(0, publishedItemCount - publishedPublicItemCount);

  return (
    <main className="dashboard-main profile-workspace">
      <section className="profile-command-strip" aria-labelledby="profile-workspace-title">
        <div>
          <p className="eyebrow">Profile workspace</p>
          <h2 id="profile-workspace-title">Review and publish profile knowledge.</h2>
          <p>
            Draft items are pending review. Published items are active for Internal JobOps context, and Public published
            items also power the portfolio and public portfolio agent.
          </p>
        </div>
        <div className="profile-status-metrics" aria-label="Profile lifecycle status">
          <SummaryMetric label="Published public" value={publishedPublicItemCount} />
          <SummaryMetric label="Published internal" value={internalPublishedCount} />
          <SummaryMetric label="Draft needs review" value={draftItemCount} />
          <SummaryMetric label="Archived" value={archivedItemCount} />
        </div>
        <div className="profile-command-actions">
          {publicPortfolioPath && publishedPublicItemCount > 0 ? (
            <a className="secondary-action" href={publicPortfolioPath}>
              Public portfolio preview
            </a>
          ) : null}
        </div>
      </section>

      {workspaceMessage ? <p className="profile-workspace-message">{workspaceMessage}</p> : null}

      <div className="profile-lifecycle-layout">
        <ReviewTabbedList
          activeLifecycle={activeLifecycle}
          activeTab={activeSection}
          draft={draft}
          editedFields={editedFields}
          intent={intent}
          onDraftItemUpdate={updateDraftItem}
          onIntentChange={updateIntent}
          onLifecycleChange={setActiveLifecycle}
          onProfileSave={updateProfileFields}
          onPublishedItemUpdate={updatePublishedItem}
          onTabChange={setActiveSection}
          profile={profile}
          publishedProfile={publishedProfile}
          publicProfile={publicProfile}
        />
        <aside className="profile-context-rail" aria-label="Profile context summaries">
          <PublicPortfolioPreview publicPortfolioPath={publicPortfolioPath} publishedPublicItemCount={publishedPublicItemCount} />
          <InternalContextSummary
            publishedItemCount={publishedItemCount}
            publishedProfile={publishedProfile}
            publishedPublicItemCount={publishedPublicItemCount}
          />
          <section className="profile-side-card">
            <p className="eyebrow">Recent changes</p>
            <ChangeSummary turn={lastTurn} />
          </section>
          <section className="profile-side-card">
            <p className="eyebrow">Follow-up queue</p>
            <ClarifyingQuestions draft={draft} />
          </section>
        </aside>
      </div>
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
      <IconBadge kind="private" label="Internal only" />
      <IconBadge kind="unpublished" label="Draft" />
    </span>
  );
}

function TargetsCard({
  editedFields,
  intent,
  onChange,
  onDraftItemUpdate
}: {
  editedFields: Set<IntentField>;
  intent: TargetRoleIntent;
  onChange: (field: IntentField, value: string) => void;
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
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
      {intent.id && intent.published !== true && intent.status !== "rejected" ? (
        <ReviewActions
          item={{
            id: intent.id,
            source: intent.source ?? "model",
            status: intent.status ?? "needs_review",
            visibility: intent.visibility ?? "private",
            published: false
          }}
          itemType="target-role"
          onDraftItemUpdate={onDraftItemUpdate}
        />
      ) : (
        <p className="profile-lifecycle-note">
          Target intent edits are saved through profile intake. Publish controls appear when a target draft row is loaded.
        </p>
      )}
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
        <label>
          <span>Telephone number</span>
          <input disabled placeholder="Private contact field schema pending" />
        </label>
        <label>
          <span>Email address</span>
          <input disabled placeholder="Private contact field schema pending" />
        </label>
        <label>
          <span>Calendly link</span>
          <input disabled placeholder="Private by default" />
        </label>
        <label>
          <span>Current location</span>
          <input disabled placeholder="Private by default" />
        </label>
        <label className="full-span">
          <span>Mailing address</span>
          <input disabled placeholder="Private cover-letter support field pending" />
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
  publishedProfile,
  publicProfile
}: {
  draft: MockProfileDraft | null;
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
  publishedProfile?: PublishedProfileSnapshot | null;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const [activeTab, setActiveTab] = useState<ReviewTabId>("experience");
  const [activeLifecycle, setActiveLifecycle] = useState<LifecycleTab>("drafts");

  if (!draft) {
    return (
      <ReviewTabbedList
        activeLifecycle={activeLifecycle}
        activeTab={activeTab}
        draft={null}
        onDraftItemUpdate={onDraftItemUpdate}
        onLifecycleChange={setActiveLifecycle}
        onTabChange={setActiveTab}
        publishedProfile={publishedProfile}
        publicProfile={publicProfile}
      />
    );
  }

  return (
    <ReviewTabbedList
      activeLifecycle={activeLifecycle}
      activeTab={activeTab}
      draft={draft}
      onDraftItemUpdate={onDraftItemUpdate}
      onLifecycleChange={setActiveLifecycle}
      onTabChange={setActiveTab}
      publishedProfile={publishedProfile}
      publicProfile={publicProfile}
    />
  );
}

export function ReviewTabbedList({
  activeLifecycle = "drafts",
  activeTab,
  draft,
  editedFields = new Set<IntentField>(),
  intent = emptyTargetRoleIntent,
  onDraftItemUpdate,
  onIntentChange,
  onLifecycleChange = () => undefined,
  onProfileSave,
  onPublishedItemUpdate,
  onTabChange,
  profile,
  publishedProfile,
  publicProfile
}: {
  activeLifecycle?: LifecycleTab;
  activeTab: ReviewTabId;
  draft: MockProfileDraft | null;
  editedFields?: Set<IntentField>;
  intent?: TargetRoleIntent;
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
  onIntentChange?: (field: IntentField, value: string) => void;
  onLifecycleChange?: (tab: LifecycleTab) => void;
  onProfileSave?: (patch: { displayName?: string; headline?: string; summary?: string }) => void;
  onPublishedItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: PublishedItemPatch) => void;
  onTabChange: (tab: ReviewTabId) => void;
  profile?: ProfileSummary | null;
  publishedProfile?: PublishedProfileSnapshot | null;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const draftCounts = buildReviewCounts(draft);
  const publishedCounts = buildPublishedReviewCounts(publishedProfile);
  const activeLabel = reviewTabs.find((tab) => tab.id === activeTab)?.label || "Profile data";

  return (
    <div className="profile-review-tabs profile-section-rail">
      <div className="profile-review-tablist" role="tablist" aria-orientation="vertical" aria-label="Profile section navigation">
        {reviewTabs.map((tab) => (
          <button
            aria-controls={`profile-review-panel-${tab.id}`}
            aria-selected={activeTab === tab.id}
            className={`profile-review-tab${tab.id === "basics" ? " profile-basics-tab" : ""}${activeTab === tab.id ? " active" : ""}`}
            id={`profile-review-tab-${tab.id}`}
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            role="tab"
            suppressHydrationWarning
            type="button"
          >
            <span>{tab.label}</span>
            <strong aria-label={`${draftCounts[tab.id]} Draft, ${publishedCounts[tab.id]} Published`}>
              <span>{draftCounts[tab.id]}</span>
              <small>{publishedCounts[tab.id]}</small>
            </strong>
          </button>
        ))}
      </div>
      <section
        aria-labelledby={`profile-review-tab-${activeTab}`}
        className="profile-review-panel profile-main-workspace"
        id={`profile-review-panel-${activeTab}`}
        role="tabpanel"
      >
        <div className="profile-review-panel-header">
          <div>
            <h3>{activeLabel}</h3>
            <p>Draft is pending review. Published is active Internal JobOps context; Public items also appear externally.</p>
          </div>
          <span>{draftCounts[activeTab]} Draft / {publishedCounts[activeTab]} Published</span>
        </div>
        <div className="profile-lifecycle-tabs" role="tablist" aria-label={`${activeLabel} lifecycle`}>
          <button
            aria-selected={activeLifecycle === "drafts"}
            className={activeLifecycle === "drafts" ? "active" : ""}
            onClick={() => onLifecycleChange("drafts")}
            role="tab"
            type="button"
          >
            Drafts
          </button>
          <button
            aria-selected={activeLifecycle === "published"}
            className={activeLifecycle === "published" ? "active" : ""}
            onClick={() => onLifecycleChange("published")}
            role="tab"
            type="button"
          >
            Published
          </button>
        </div>
        <section className="profile-review-card" aria-label={`${activeLifecycle === "drafts" ? "Draft" : "Published"} ${activeLabel}`}>
          <div className="profile-review-card-header">
            <h4>{activeLifecycle === "drafts" ? "Draft" : "Published"}</h4>
            <span>{activeLifecycle === "drafts" ? `${draftCounts[activeTab]} Draft` : `${publishedCounts[activeTab]} Published`}</span>
          </div>
          {activeLifecycle === "drafts" ? (
            <ProfileReviewTabContent
              activeTab={activeTab}
              draft={draft}
              editedFields={editedFields}
              intent={intent}
              onDraftItemUpdate={onDraftItemUpdate}
              onIntentChange={onIntentChange}
              onProfileSave={onProfileSave}
              profile={profile ?? null}
            />
          ) : (
            <PublishedProfileTabContent
              activeTab={activeTab}
              onPublishedItemUpdate={onPublishedItemUpdate}
              publishedProfile={publishedProfile}
              publicProfile={publicProfile}
            />
          )}
        </section>
      </section>
    </div>
  );
}

function ProfileReviewTabContent({
  activeTab,
  draft,
  editedFields,
  intent,
  onProfileSave,
  onIntentChange,
  onDraftItemUpdate,
  profile
}: {
  activeTab: ReviewTabId;
  draft: MockProfileDraft | null;
  editedFields: Set<IntentField>;
  intent: TargetRoleIntent;
  onProfileSave?: (patch: { displayName?: string; headline?: string; summary?: string }) => void;
  onIntentChange?: (field: IntentField, value: string) => void;
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
  profile: ProfileSummary | null;
}) {
  if (activeTab === "basics") {
    return onProfileSave ? <ProfileBasicsPanel onSave={onProfileSave} profile={profile} /> : <EmptyMessage>No profile basics loaded yet.</EmptyMessage>;
  }

  if (activeTab === "targets") {
    return onIntentChange ? (
      <TargetsCard editedFields={editedFields} intent={intent} onChange={onIntentChange} onDraftItemUpdate={onDraftItemUpdate} />
    ) : (
      <EmptyMessage>No target draft loaded yet.</EmptyMessage>
    );
  }

  if (!draft) {
    return <EmptyReviewList activeTab={activeTab} />;
  }

  if (activeTab === "experience") {
    const items = draft.experienceSummaries.filter(
      (item) => isPendingDraftItem(item) && (item.itemType === "experience" || item.itemType === "project")
    );
    return <ExperienceList emptyLabel="No experience or project items drafted yet." items={items} onDraftItemUpdate={onDraftItemUpdate} showType />;
  }

  if (activeTab === "education") {
    return (
      <ExperienceList
        emptyLabel="No education items drafted yet."
        items={draft.experienceSummaries.filter((item) => isPendingDraftItem(item) && item.itemType === "education")}
        onDraftItemUpdate={onDraftItemUpdate}
      />
    );
  }

  if (activeTab === "certifications") {
    return (
      <ExperienceList
        emptyLabel="No certification items drafted yet."
        items={draft.experienceSummaries.filter((item) => isPendingDraftItem(item) && item.itemType === "certification")}
        onDraftItemUpdate={onDraftItemUpdate}
      />
    );
  }

  if (activeTab === "skills") {
    const skills = draft.skillClaims.filter(isPendingDraftItem);
    return skills.length ? (
      <ul className="profile-review-list">
        {skills.map((skill) => (
          <li className="profile-review-item profile-review-row draft-review-card" key={skill.id}>
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
    const achievements = draft.facts.filter((fact) => isPendingDraftItem(fact) && looksLikeAchievement(fact.claim, fact.category));
    return achievements.length ? <FactList facts={achievements} onDraftItemUpdate={onDraftItemUpdate} /> : <EmptyMessage>No achievement or outcome items drafted yet.</EmptyMessage>;
  }

  if (activeTab === "facts") {
    const facts = draft.facts.filter(isPendingDraftItem);
    return facts.length ? <FactList facts={facts} onDraftItemUpdate={onDraftItemUpdate} /> : <EmptyMessage>No facts or claims drafted yet.</EmptyMessage>;
  }

  const links = draft.links.filter(isPendingDraftItem);
  return links.length ? (
    <ul className="profile-review-list">
      {links.map((link) => (
        <li className="profile-review-item profile-review-row draft-review-card" key={link.id}>
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
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
  showType?: boolean;
}) {
  if (!items.length) {
    return <EmptyMessage>{emptyLabel}</EmptyMessage>;
  }

  return (
    <ul className="profile-review-list">
      {items.map((experience) => (
        <li className="profile-review-item draft-review-card" key={experience.id}>
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
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
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
  onPublishedItemUpdate,
  publishedProfile,
  publicProfile
}: {
  activeTab: ReviewTabId;
  onPublishedItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: PublishedItemPatch) => void;
  publishedProfile?: PublishedProfileSnapshot | null;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const profile = publishedProfile ?? publicProfile;
  if (!profile) {
    return <EmptyMessage>No published profile loaded yet.</EmptyMessage>;
  }

  if (activeTab === "basics") {
    return <PublishedBasics publishedProfile={profile} />;
  }

  if (activeTab === "targets") {
    return <PublishedTargets onPublishedItemUpdate={onPublishedItemUpdate} publishedProfile={profile} />;
  }

  if (activeTab === "skills") {
    const skills = profile.skillClaims ?? [];
    return skills.length ? (
      <ul className="profile-review-list">
        {skills.map((skill) => (
          <li className="profile-review-item" key={skill.id}>
            <TitleWithBadges title={skill.skill}>
              <VisibilityTextBadge visibility={skill.visibility} />
            </TitleWithBadges>
            <span>{skill.category}</span>
            {skill.evidence ? <p>{skill.evidence}</p> : null}
            <PublishedActions itemId={skill.id} itemType="skill" onPublishedItemUpdate={onPublishedItemUpdate} visibility={skill.visibility} />
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
    const items = (profile.experienceAndProjects ?? []).filter((item) => itemTypes.includes(item.itemType || "experience"));
    return items.length ? (
      <ul className="profile-review-list">
        {items.map((item) => (
          <li className="profile-review-item" key={item.id}>
            <TitleWithBadges title={item.title}>
              <VisibilityTextBadge visibility={item.visibility} />
            </TitleWithBadges>
            {item.organization ? <span>{item.organization}</span> : null}
            <p>{item.summary}</p>
            <PublishedActions itemId={item.id} itemType="experience" onPublishedItemUpdate={onPublishedItemUpdate} visibility={item.visibility} />
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No published {reviewTabs.find((tab) => tab.id === activeTab)?.label.toLowerCase()} yet.</EmptyMessage>
    );
  }

  if (activeTab === "evidence") {
    const links = profile.evidenceLinks ?? [];
    return links.length ? (
      <ul className="profile-review-list">
        {links.map((link) => (
          <li className="profile-review-item" key={link.id}>
            <TitleWithBadges title={link.label}>
              <VisibilityTextBadge visibility={link.visibility} />
            </TitleWithBadges>
            <a href={link.url} rel="noreferrer" target="_blank">
              {link.url}
            </a>
            <PublishedActions itemId={link.id} itemType="evidence" onPublishedItemUpdate={onPublishedItemUpdate} visibility={link.visibility} />
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No published evidence links yet.</EmptyMessage>
    );
  }

  const facts = (profile.facts ?? []).filter((fact) =>
    activeTab === "achievements" ? looksLikeAchievement(fact.claim, fact.category) : true
  );
  return facts.length ? (
    <ul className="profile-review-list">
      {facts.map((fact) => (
        <li className="profile-review-item" key={fact.id}>
          <TitleWithBadges title={fact.category}>
            <VisibilityTextBadge visibility={fact.visibility} />
          </TitleWithBadges>
          <span>{fact.claim}</span>
          <PublishedActions itemId={fact.id} itemType="fact" onPublishedItemUpdate={onPublishedItemUpdate} visibility={fact.visibility} />
        </li>
      ))}
    </ul>
  ) : (
    <EmptyMessage>No published {activeTab === "achievements" ? "achievements" : "facts"} yet.</EmptyMessage>
  );
}

function PublishedBasics({ publishedProfile }: { publishedProfile: PublishedProfileSnapshot }) {
  return (
    <div className="profile-summary-grid">
      <SummaryText label="Display name" value={publishedProfile.displayName ?? "Not set"} />
      <SummaryText label="Headline" value={publishedProfile.headline ?? "Not set"} />
      <SummaryText label="Summary" value={publishedProfile.summary ?? "Not set"} />
      <p className="profile-lifecycle-note">
        Contact fields are intentionally private by default. Public exposure needs explicit published public support before
        those details appear on the portfolio.
      </p>
    </div>
  );
}

function SummaryText({ label, value }: { label: string; value: string }) {
  return (
    <div className="profile-summary-text">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PublishedTargets({
  onPublishedItemUpdate,
  publishedProfile
}: {
  onPublishedItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: PublishedItemPatch) => void;
  publishedProfile: PublishedProfileSnapshot;
}) {
  const target = publishedProfile.targetRoleIntent;
  if (!target || !hasTargetRoleIntent(target)) {
    return <EmptyMessage>No published targets yet.</EmptyMessage>;
  }

  return (
    <div className="published-target-card">
      <VisibilityTextBadge visibility={target.visibility ?? "private"} />
      <DetailGrid
        items={[
          ["Target titles", (target.targetTitles ?? []).join(", ")],
          ["Role families", (target.roleFamilies ?? []).join(", ")],
          ["Work modes", (target.workModes ?? []).join(", ")],
          ["Locations", (target.preferredLocations ?? []).join(", ")],
          ["Domains", target.domainsOrIndustries ?? ""]
        ]}
      />
      {target.id ? (
        <PublishedActions
          itemId={target.id}
          itemType="target-role"
          onPublishedItemUpdate={onPublishedItemUpdate}
          visibility={target.visibility ?? "private"}
        />
      ) : null}
    </div>
  );
}

function PublicPortfolioPreview({
  publicPortfolioPath,
  publishedPublicItemCount
}: {
  publicPortfolioPath: string | null;
  publishedPublicItemCount: number;
}) {
  const previewPath = publicPortfolioPath || "/portfolio";
  return (
    <section className="profile-side-card public-preview-card">
      <div className="profile-side-card-header">
        <div>
          <p className="eyebrow">Public portfolio preview</p>
          <h3>Live published-public view</h3>
        </div>
        <a href={previewPath}>Open</a>
      </div>
      <div className="portfolio-preview-frame-wrap">
        <iframe
          className="portfolio-preview-frame"
          src={previewPath}
          title="Public portfolio preview"
        />
      </div>
      <p className="profile-lifecycle-note">
        This preview uses the public portfolio route and should only show Published Public items. Published public item
        count: {publishedPublicItemCount}.
      </p>
    </section>
  );
}

function InternalContextSummary({
  publishedItemCount,
  publishedProfile,
  publishedPublicItemCount
}: {
  publishedItemCount: number;
  publishedProfile: PublishedProfileSnapshot | null;
  publishedPublicItemCount: number;
}) {
  const internalOnlyCount = Math.max(0, publishedItemCount - publishedPublicItemCount);
  return (
    <section className="profile-side-card">
      <p className="eyebrow">Internal JobOps context</p>
      <h3>Published knowledge active internally</h3>
      <div className="profile-summary-grid compact">
        <SummaryMetric label="Published" value={publishedItemCount} />
        <SummaryMetric label="Internal only" value={internalOnlyCount || countVisibility(publishedProfile, "private")} />
        <SummaryMetric label="Public" value={publishedPublicItemCount} />
      </div>
      <p className="profile-lifecycle-note">
        Internal JobOps context includes published Internal only and published Public items. Drafts are reserved for
        profile editing and review flows.
      </p>
    </section>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="profile-summary-metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function VisibilityTextBadge({ visibility }: { visibility: "private" | "public" }) {
  return <span className={`visibility-text-badge ${visibility}`}>{visibility === "public" ? "Public" : "Internal only"}</span>;
}

function EditableFactRow({
  fact,
  onDraftItemUpdate
}: {
  fact: MockProfileDraft["facts"][number];
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
}) {
  const [claim, setClaim] = useState(fact.claim);
  const [category, setCategory] = useState(fact.category);

  useEffect(() => {
    setClaim(fact.claim);
    setCategory(fact.category);
  }, [fact]);

  return (
    <li className="profile-review-item fact-edit-row draft-review-card">
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
  itemType: ProfileItemType;
  onDraftItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => void;
}) {
  return (
    <div className="review-action-row">
      <button
        className="secondary-action button-action"
        disabled={!onDraftItemUpdate || item.published}
        onClick={() => onDraftItemUpdate?.(itemType, item.id, { publishVisibility: "private" })}
        type="button"
      >
        Publish internal
      </button>
      <button
        className="secondary-action button-action"
        disabled={!onDraftItemUpdate || item.published}
        onClick={() => onDraftItemUpdate?.(itemType, item.id, { publishVisibility: "public" })}
        type="button"
      >
        Publish public
      </button>
      <button
        className="secondary-action button-action subtle-danger"
        disabled={!onDraftItemUpdate || item.published}
        onClick={() => onDraftItemUpdate?.(itemType, item.id, { reviewStatus: "rejected", visibility: "private" })}
        type="button"
      >
        Archive
      </button>
    </div>
  );
}

function PublishedActions({
  itemId,
  itemType,
  onPublishedItemUpdate,
  visibility
}: {
  itemId: string;
  itemType: ProfileItemType;
  onPublishedItemUpdate?: (itemType: ProfileItemType, itemId: string, patch: PublishedItemPatch) => void;
  visibility: "private" | "public";
}) {
  return (
    <div className="review-action-row published-action-row">
      <button
        className="secondary-action button-action"
        disabled={!onPublishedItemUpdate || visibility === "private"}
        onClick={() => onPublishedItemUpdate?.(itemType, itemId, { visibility: "private" })}
        type="button"
      >
        Internal only
      </button>
      <button
        className="secondary-action button-action"
        disabled={!onPublishedItemUpdate || visibility === "public"}
        onClick={() => onPublishedItemUpdate?.(itemType, itemId, { visibility: "public" })}
        type="button"
      >
        Public
      </button>
      <button
        className="secondary-action button-action subtle-danger"
        disabled={!onPublishedItemUpdate}
        onClick={() => onPublishedItemUpdate?.(itemType, itemId, { archive: true })}
        type="button"
      >
        Archive
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
  const facts = draft?.facts.filter(isPendingDraftItem) ?? [];
  const skills = draft?.skillClaims.filter(isPendingDraftItem) ?? [];
  const experience = draft?.experienceSummaries.filter(isPendingDraftItem) ?? [];
  const links = draft?.links.filter(isPendingDraftItem) ?? [];
  const targets = draft && hasTargetIntentDraft(draft) ? 1 : 0;
  const counts = {
    basics: 0,
    targets,
    experience: experience.filter((item) => item.itemType === "experience" || item.itemType === "project").length,
    skills: skills.length,
    achievements: facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category)).length,
    facts: facts.length,
    evidence: links.length,
    education: experience.filter((item) => item.itemType === "education").length,
    certifications: experience.filter((item) => item.itemType === "certification").length
  };
  return counts;
}

function buildPublishedReviewCounts(publishedProfile?: PublishedProfileSnapshot | null): Record<ReviewTabId, number> {
  const facts = publishedProfile?.facts ?? [];
  const experience = publishedProfile?.experienceAndProjects ?? [];
  const counts = {
    basics: publishedProfile ? 1 : 0,
    targets: hasTargetRoleIntent(publishedProfile?.targetRoleIntent) ? 1 : 0,
    experience: experience.filter((item) => (item.itemType || "experience") === "experience" || item.itemType === "project").length,
    skills: publishedProfile?.skillClaims?.length ?? 0,
    achievements: facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category)).length,
    facts: facts.length,
    evidence: publishedProfile?.evidenceLinks?.length ?? 0,
    education: experience.filter((item) => item.itemType === "education").length,
    certifications: experience.filter((item) => item.itemType === "certification").length
  };
  return counts;
}

function totalDraftCount(draft: MockProfileDraft | null) {
  const counts = buildReviewCounts(draft);
  return reviewTabs.filter((tab) => tab.id !== "basics").reduce((sum, tab) => sum + counts[tab.id], 0);
}

function buildDraftActionMessage(patch: DraftItemPatch) {
  if (patch.publishVisibility === "public") {
    return "Draft item published public.";
  }
  if (patch.publishVisibility === "private") {
    return "Draft item published internal.";
  }
  if (patch.reviewStatus === "rejected") {
    return "Draft item archived.";
  }
  return "Draft item updated.";
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
  return <IconBadge kind={published ? "published" : "unpublished"} label={published ? "Published" : "Draft"} />;
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
  return visibility === "private" ? "Internal only" : "Public";
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

function isPendingDraftItem(item: BadgeableDraftItem) {
  return !item.published && item.status !== "rejected";
}

function hasTargetIntentDraft(draft: MockProfileDraft | null) {
  return Boolean(draft && (draft.facts.length || draft.skillClaims.length || draft.experienceSummaries.length || draft.links.length));
}

function hasTargetRoleIntent(target?: PublicProfileSnapshot["targetRoleIntent"]) {
  return Boolean(
    target &&
      [
        ...(target.targetTitles ?? []),
        ...(target.roleFamilies ?? []),
        ...(target.preferredLocations ?? []),
        ...(target.workModes ?? []),
        target.domainsOrIndustries ?? ""
      ].some((value) => value.trim().length > 0)
  );
}

function countVisibility(profile: PublishedProfileSnapshot | null | undefined, visibility: "private" | "public") {
  if (!profile) {
    return 0;
  }
  return [
    ...(profile.facts ?? []),
    ...(profile.skillClaims ?? []),
    ...(profile.experienceAndProjects ?? []),
    ...(profile.evidenceLinks ?? []),
    ...(profile.targetRoleIntent?.visibility ? [profile.targetRoleIntent] : [])
  ].filter((item) => item.visibility === visibility).length;
}

function looksLikeAchievement(claim: string, category: string) {
  const normalized = `${claim} ${category}`.toLowerCase();
  return /%|\d|reduced|improved|increased|launched|shipped|built|deployed|optimized|scaled|throughput|hours|minutes/.test(
    normalized
  );
}
