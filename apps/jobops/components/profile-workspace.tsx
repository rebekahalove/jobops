"use client";

import React, { useEffect, useId, useRef, useState } from "react";
import type { ProfileIntakeOutput } from "../lib/profile-intake-contract";
import {
  applyProfileIntakeOutputToState,
  emptyTargetRoleIntent,
  type MockIntakeTurn,
  type MockProfileDraft
} from "../lib/profile-intake";

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

type LifecycleTab = "generated" | "private" | "archived";

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

type WorkspaceMessage = {
  kind: "success" | "error" | "info";
  text: string;
};

type ProfileWorkspacePayload = {
  profile?: ProfileSummary;
  draft: ProfileIntakeOutput & { statusSummary?: string };
  publishedProfile?: PublishedProfileSnapshot;
  publicProfile?: PublicProfileSnapshot;
  profileFields?: ProfileFieldGroups;
  publicPortfolioPath?: string;
  publishedItemCount?: number;
  publishedPublicItemCount?: number;
  archivedItemCount?: number;
  devTools?: {
    profileItemClearEnabled?: boolean;
  };
};

type ProfileFieldGroups = {
  profileBasics: ProfileFieldState[];
  targets: ProfileFieldState[];
};

type ProfileFieldValue = {
  id: string;
  value: string;
  source: string;
  lifecycleStatus: "generated" | "published" | "archived";
  visibility?: "private" | "public" | null;
  archiveReason?: string | null;
  originalValue?: string | null;
};

type ProfileFieldState = {
  group: "profile_basics" | "targets";
  name: string;
  label: string;
  publicAllowed: boolean;
  privateOnly: boolean;
  multiline: boolean;
  generated?: ProfileFieldValue | null;
  published?: ProfileFieldValue | null;
  archived: ProfileFieldValue[];
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
    yearsMin?: number | null;
    yearsMax?: number | null;
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
    constraints?: string;
    visibility?: "private" | "public";
    publicationStatus?: string;
  };
  profileFields?: {
    profileBasics?: Record<string, string>;
    targets?: Record<string, string>;
  };
};

type PublishedProfileSnapshot = PublicProfileSnapshot;

type DraftItemPatch = {
  claim?: string;
  category?: string;
  skill?: string;
  evidence?: string;
  yearsMin?: number | null;
  yearsMax?: number | null;
  title?: string;
  organization?: string;
  startDate?: string;
  endDate?: string;
  location?: string;
  summary?: string;
  bullets?: string[];
  url?: string;
  label?: string;
  visibility?: "private" | "public";
  reviewStatus?: MockProfileDraft["facts"][number]["status"];
  publishVisibility?: "private" | "public";
};

type ProfileItemType = "fact" | "skill" | "experience" | "evidence";

type PublishedItemPatch = {
  claim?: string;
  category?: string;
  skill?: string;
  evidence?: string;
  yearsMin?: number | null;
  yearsMax?: number | null;
  title?: string;
  organization?: string;
  startDate?: string;
  endDate?: string;
  location?: string;
  summary?: string;
  bullets?: string[];
  url?: string;
  label?: string;
  visibility?: "private" | "public";
  archive?: boolean;
};

type ProfileFieldPatch = {
  value?: string;
  lifecycleStatus?: "generated" | "published";
  publishVisibility?: "private" | "public";
  visibility?: "private" | "public";
  archive?: boolean;
};

type DraftItemUpdateHandler = (itemType: ProfileItemType, itemId: string, patch: DraftItemPatch) => Promise<boolean> | boolean | void;
type PublishedItemUpdateHandler = (itemType: ProfileItemType, itemId: string, patch: PublishedItemPatch) => Promise<boolean> | boolean | void;
type ProfileFieldUpdateHandler = (fieldGroup: ProfileFieldState["group"], fieldName: string, patch: ProfileFieldPatch) => Promise<boolean> | boolean | void;

const publicProfileBasicPreviewLabels: Record<string, string> = {
  displayName: "Name",
  headline: "Headline",
  summary: "Summary",
  emailAddress: "Email address",
  telephoneNumber: "Telephone number",
  calendlyLink: "Calendly link",
  currentLocation: "Current location"
};

const publicTargetPreviewLabels: Record<string, string> = {
  targetTitles: "Target titles",
  roleFamilies: "Target role families",
  preferredWorkMode: "Preferred work mode",
  preferredLocations: "Preferred locations",
  domainsOrIndustries: "Domains or industries",
  constraints: "Constraints"
};

export function ProfileWorkspace({ apiBasePath = "/api" }: { apiBasePath?: string }) {
  const [draft, setDraft] = useState<MockProfileDraft | null>(null);
  const [publishedProfile, setPublishedProfile] = useState<PublishedProfileSnapshot | null>(null);
  const [publicProfile, setPublicProfile] = useState<PublicProfileSnapshot | null>(null);
  const [profileFields, setProfileFields] = useState<ProfileFieldGroups | null>(null);
  const [publicPortfolioPath, setPublicPortfolioPath] = useState<string | null>(null);
  const [publishedItemCount, setPublishedItemCount] = useState(0);
  const [publishedPublicItemCount, setPublishedPublicItemCount] = useState(0);
  const [lastTurn, setLastTurn] = useState<MockIntakeTurn | null>(null);
  const [workspaceMessage, setWorkspaceMessage] = useState<WorkspaceMessage | null>(null);
  const [activeSection, setActiveSection] = useState<ReviewTabId>("basics");
  const [activeLifecycle, setActiveLifecycle] = useState<LifecycleTab>("generated");
  const [profileItemClearEnabled, setProfileItemClearEnabled] = useState(false);
  const [clearingProfileItems, setClearingProfileItems] = useState(false);

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
    setDraft(nextState.draft);
    setLastTurn(nextState.turn);
    setPublishedProfile(result.publishedProfile ?? null);
    setPublicProfile(result.publicProfile ?? null);
    setProfileFields(result.profileFields ?? null);
    setPublicPortfolioPath(result.publicPortfolioPath ?? null);
    setPublishedItemCount(result.publishedItemCount ?? 0);
    setPublishedPublicItemCount(result.publishedPublicItemCount ?? 0);
    setProfileItemClearEnabled(result.devTools?.profileItemClearEnabled === true);
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

  useEffect(() => {
    if (!workspaceMessage) {
      return;
    }
    const timeout = window.setTimeout(() => setWorkspaceMessage(null), workspaceMessage.kind === "error" ? 9000 : 5200);
    return () => window.clearTimeout(timeout);
  }, [workspaceMessage]);

  function showWorkspaceMessage(text: string, kind: WorkspaceMessage["kind"] = "info") {
    setWorkspaceMessage({ kind, text });
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
      showWorkspaceMessage(payload.ok === false ? payload.error : "Generated item update failed.", "error");
      return false;
    }
    applyProfilePayload(payload.result);
    showWorkspaceMessage(buildDraftActionMessage(patch), "success");
    return true;
  }

  async function updatePublishedItem(itemType: ProfileItemType, itemId: string, patch: PublishedItemPatch) {
    const response = await fetch(`${apiBasePath}/profile/published-items/${itemType}/${itemId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(patch)
    });
    const payload = (await response.json()) as { ok: true; result: ProfileWorkspacePayload } | { ok: false; error?: string; detail?: string };
    if (!response.ok || !payload.ok) {
      const error = payload.ok === false ? (payload.error || payload.detail || "Published item update failed.") : "Published item update failed.";
      showWorkspaceMessage(error, "error");
      return false;
    }
    applyProfilePayload(payload.result);
    showWorkspaceMessage(buildPublishedActionMessage(patch), "success");
    return true;
  }

  async function updateProfileField(fieldGroup: ProfileFieldState["group"], fieldName: string, patch: ProfileFieldPatch) {
    const response = await fetch(`${apiBasePath}/profile/fields/${fieldGroup}/${fieldName}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(patch)
    });
    const payload = (await response.json()) as { ok: true; result: ProfileWorkspacePayload } | { ok: false; error?: string; detail?: string };
    if (!response.ok || !payload.ok) {
      const error = payload.ok === false ? (payload.error || payload.detail || "Profile field update failed.") : "Profile field update failed.";
      showWorkspaceMessage(error, "error");
      return false;
    }
    applyProfilePayload(payload.result);
    showWorkspaceMessage(buildProfileFieldActionMessage(patch), "success");
    return true;
  }

  async function clearProfileItems() {
    if (clearingProfileItems) {
      return;
    }
    const confirmed = window.confirm(
      "Clear all generated, published, and archived profile items for your current profile? This cannot be undone."
    );
    if (!confirmed) {
      return;
    }

    setClearingProfileItems(true);
    try {
      const response = await fetch(`${apiBasePath}/profile/clear-items`, {
        method: "DELETE"
      });
      const payload = (await response.json()) as { ok: true; result: ProfileWorkspacePayload } | { ok: false; error?: string; detail?: string };
      if (!response.ok || !payload.ok) {
        const error = payload.ok === false ? (payload.error || payload.detail || "Profile clear failed.") : "Profile clear failed.";
        showWorkspaceMessage(error, "error");
        return;
      }
      applyProfilePayload(payload.result);
      setActiveLifecycle("generated");
      showWorkspaceMessage("Profile workspace items cleared for this user.", "success");
    } catch {
      showWorkspaceMessage("Profile clear failed. Try again after the API is available.", "error");
    } finally {
      setClearingProfileItems(false);
    }
  }

  function startPublishedEdit() {
    showWorkspaceMessage("Editing published items will create a generated replacement item in a follow-up slice.", "info");
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
            Generated items are pending review. Private items are active for private JobOps context, and Public items
            power the portfolio and public portfolio agent.
          </p>
        </div>
        <div className="profile-header-actions">
          <div className="profile-status-metrics" aria-label="Profile lifecycle status">
            <SummaryMetric label="Generated needs review" value={draftItemCount} />
            <SummaryMetric label="Published private" value={internalPublishedCount} />
            <SummaryMetric label="Published public" value={publishedPublicItemCount} />
          </div>
          {profileItemClearEnabled ? (
            <button
              className="button-action subtle-danger profile-clear-button"
              disabled={clearingProfileItems}
              onClick={clearProfileItems}
              type="button"
            >
              {clearingProfileItems ? "Clearing..." : "Clear"}
            </button>
          ) : null}
        </div>
        <section className="profile-header-recent" aria-label="Recent profile changes">
          <p className="eyebrow">Recent changes</p>
          <ChangeSummary turn={lastTurn} />
        </section>
      </section>

      {workspaceMessage ? <p className={`profile-workspace-message ${workspaceMessage.kind}`}>{workspaceMessage.text}</p> : null}

      <div className="profile-lifecycle-layout">
        <ReviewTabbedList
          activeLifecycle={activeLifecycle}
          activeTab={activeSection}
          draft={draft}
          onDraftItemUpdate={updateDraftItem}
          onLifecycleChange={setActiveLifecycle}
          onPublishedEdit={startPublishedEdit}
          onPublishedItemUpdate={updatePublishedItem}
          onProfileFieldUpdate={updateProfileField}
          onTabChange={setActiveSection}
          profileFields={profileFields}
          publishedProfile={publishedProfile}
          publicProfile={publicProfile}
        />
        <aside className="profile-context-rail" aria-label="Profile context summaries">
          <PublicPortfolioPreview
            onEdit={startPublishedEdit}
            onProfileFieldUpdate={updateProfileField}
            onPublishedItemUpdate={updatePublishedItem}
            publicPortfolioPath={publicPortfolioPath}
            publicProfile={publicProfile}
            publishedPublicItemCount={publishedPublicItemCount}
          />
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

function FieldGroupPanel({
  fields,
  lifecycle,
  onProfileFieldUpdate
}: {
  fields: ProfileFieldState[];
  lifecycle: LifecycleTab;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
}) {
  if (!fields.length) {
    return <EmptyMessage>No field-level profile data loaded yet.</EmptyMessage>;
  }
  const visibleRows = fieldLifecycleRows(fields, lifecycle);
  if (!visibleRows.length) {
    return <EmptyMessage>{emptyFieldGroupMessage(lifecycle)}</EmptyMessage>;
  }

  return (
    <ul className="profile-review-list field-group-list">
      {visibleRows.map(({ field, value, rowKey }) => (
        <FieldLifecycleRow
          field={field}
          key={rowKey}
          lifecycle={lifecycle}
          onProfileFieldUpdate={onProfileFieldUpdate}
          value={value}
        />
      ))}
    </ul>
  );
}

function fieldLifecycleRows(fields: ProfileFieldState[], lifecycle: LifecycleTab) {
  if (lifecycle === "generated") {
    return fields
      .filter((field) => field.generated)
      .map((field) => ({
        field,
        rowKey: `${field.group}-${field.name}-generated`,
        value: field.generated ?? null
      }));
  }

  if (lifecycle === "archived") {
    return fields.flatMap((field) =>
      field.archived
        .filter(isDisplayableArchivedFieldValue)
        .map((value) => ({
          field,
          rowKey: `${field.group}-${field.name}-archived-${value.id}`,
          value
        }))
    );
  }

  return fields
    .filter((field) => field.published?.visibility === "private")
    .map((field) => ({
      field,
      rowKey: `${field.group}-${field.name}-private`,
      value: field.published ?? null
    }));
}

function isDisplayableArchivedFieldValue(value: ProfileFieldValue) {
  return value.value.trim().length > 0 || (value.originalValue ?? "").trim().length > 0;
}

function emptyFieldGroupMessage(lifecycle: LifecycleTab) {
  if (lifecycle === "generated") {
    return "No generated field proposals yet.";
  }
  if (lifecycle === "archived") {
    return "No archived field values yet.";
  }
  return "No private field values in this section. Public values are managed in the preview.";
}

function FieldLifecycleRow({
  field,
  lifecycle,
  onProfileFieldUpdate,
  value: activeValue
}: {
  field: ProfileFieldState;
  lifecycle: LifecycleTab;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
  value: ProfileFieldValue | null;
}) {
  const value = activeValue?.value ?? "";
  const editable = lifecycle !== "archived";
  const publishedVisibility = activeValue?.visibility ?? null;

  return (
    <li className={`profile-review-item editable-review-card field-lifecycle-row ${lifecycle}`}>
      <div className="field-lifecycle-header">
        <div className="field-lifecycle-title">
          <strong>{field.label}</strong>
          <FieldLifecycleBadges field={field} lifecycle={lifecycle} value={activeValue} />
        </div>
        <FieldLifecycleActions
          field={field}
          lifecycle={lifecycle}
          onProfileFieldUpdate={onProfileFieldUpdate}
          publishedVisibility={publishedVisibility}
          value={activeValue}
        />
      </div>
      {editable ? (
        <CompactEditableField
          label={field.label}
          multiline={field.multiline}
          onSave={(nextValue) =>
            onProfileFieldUpdate?.(field.group, field.name, {
              lifecycleStatus: lifecycle === "private" ? "published" : "generated",
              value: nextValue
            })
          }
          value={value}
        />
      ) : (
        <p className="archived-field-value">{value || "Blank value"}</p>
      )}
    </li>
  );
}

function FieldLifecycleBadges({
  field,
  lifecycle,
  value
}: {
  field: ProfileFieldState;
  lifecycle: LifecycleTab;
  value?: ProfileFieldValue | null;
}) {
  return (
    <span className="icon-badge-row">
      {lifecycle === "generated" ? (
        value?.source === "user" ? <IconBadge kind="user" label="Edited" /> : <IconBadge kind="agent" label="Generated" />
      ) : null}
      {lifecycle === "archived" ? <IconBadge kind="unpublished" label="Archived" /> : null}
      {lifecycle === "private" && value?.visibility ? <VisibilityIcon visibility={value.visibility} /> : null}
      {field.privateOnly ? <span className="visibility-text-badge private">Private only</span> : null}
      {lifecycle === "archived" && value?.archiveReason ? (
        <span className="visibility-text-badge archived-reason">Archived: {value.archiveReason}</span>
      ) : null}
    </span>
  );
}

function FieldLifecycleActions({
  field,
  lifecycle,
  onProfileFieldUpdate,
  publishedVisibility,
  value
}: {
  field: ProfileFieldState;
  lifecycle: LifecycleTab;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
  publishedVisibility?: "private" | "public" | null;
  value?: ProfileFieldValue | null;
}) {
  if (lifecycle === "archived") {
    return null;
  }
  if (lifecycle === "private" && !value) {
    return null;
  }
  if (lifecycle === "generated") {
    return (
      <div className="review-action-row field-action-row">
        <button
          className="secondary-action button-action"
          disabled={!onProfileFieldUpdate || !value}
          onClick={() => onProfileFieldUpdate?.(field.group, field.name, { publishVisibility: "private" })}
          type="button"
        >
          Publish private
        </button>
        {field.publicAllowed ? (
          <button
            className="secondary-action button-action"
            disabled={!onProfileFieldUpdate || !value}
            onClick={() => onProfileFieldUpdate?.(field.group, field.name, { publishVisibility: "public" })}
            type="button"
          >
            Publish public
          </button>
        ) : null}
        <button
          className="secondary-action button-action subtle-danger"
          disabled={!onProfileFieldUpdate || !value}
          onClick={() => onProfileFieldUpdate?.(field.group, field.name, { archive: true, lifecycleStatus: "generated" })}
          type="button"
        >
          Archive
        </button>
      </div>
    );
  }

  return (
    <div className="review-action-row field-action-row">
      {field.publicAllowed && publishedVisibility === "private" ? (
        <button
          className="secondary-action button-action"
          disabled={!onProfileFieldUpdate || !value}
          onClick={() => onProfileFieldUpdate?.(field.group, field.name, { visibility: "public" })}
          type="button"
        >
          Make public
        </button>
      ) : null}
      <button
        className="secondary-action button-action subtle-danger"
        disabled={!onProfileFieldUpdate || !value}
        onClick={() => onProfileFieldUpdate?.(field.group, field.name, { archive: true, lifecycleStatus: "published" })}
        type="button"
      >
        Archive
      </button>
    </div>
  );
}

function ChangeSummary({ turn }: { turn: MockIntakeTurn | null }) {
  if (!turn) {
    return (
      <div className="empty-state-block">
        <h3>No changes yet</h3>
        <p>Use the JobOps command center above to update your generated profile items.</p>
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
  onDraftItemUpdate?: DraftItemUpdateHandler;
  publishedProfile?: PublishedProfileSnapshot | null;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const [activeTab, setActiveTab] = useState<ReviewTabId>("experience");
  const [activeLifecycle, setActiveLifecycle] = useState<LifecycleTab>("generated");

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
  activeLifecycle = "generated",
  activeTab,
  draft,
  onDraftItemUpdate,
  onLifecycleChange = () => undefined,
  onPublishedEdit,
  onProfileFieldUpdate,
  onPublishedItemUpdate,
  onTabChange,
  profileFields,
  publishedProfile,
  publicProfile
}: {
  activeLifecycle?: LifecycleTab;
  activeTab: ReviewTabId;
  draft: MockProfileDraft | null;
  onDraftItemUpdate?: DraftItemUpdateHandler;
  onLifecycleChange?: (tab: LifecycleTab) => void;
  onPublishedEdit?: () => void;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
  onPublishedItemUpdate?: PublishedItemUpdateHandler;
  onTabChange: (tab: ReviewTabId) => void;
  profileFields?: ProfileFieldGroups | null;
  publishedProfile?: PublishedProfileSnapshot | null;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const draftCounts = buildReviewCounts(draft);
  const privateCounts = buildPublishedReviewCounts(publishedProfile, "private");
  const publicCounts = buildPublishedReviewCounts(publicProfile ?? publishedProfile, "public");
  const archivedCounts = buildArchivedReviewCounts(draft);
  const fieldCounts = buildFieldReviewCounts(profileFields);
  const generatedCounts = { ...draftCounts, ...fieldCounts.generated };
  const publishedPrivateCounts = { ...privateCounts, ...fieldCounts.published };
  const publishedPublicCounts = { ...publicCounts, ...fieldCounts.public };
  const activeLabel = reviewTabs.find((tab) => tab.id === activeTab)?.label || "Profile data";
  const showArchivedTab = true;
  const effectiveLifecycle = activeLifecycle;
  const fieldGroup = activeTab === "basics" ? "profile_basics" : activeTab === "targets" ? "targets" : null;

  return (
    <div className="profile-review-tabs profile-section-rail">
      <div className="profile-review-tablist" role="tablist" aria-orientation="vertical" aria-label="Profile section navigation">
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
            <strong
              aria-label={`${generatedCounts[tab.id]} Generated, ${publishedPrivateCounts[tab.id]} Private, ${publishedPublicCounts[tab.id]} Public`}
              className="profile-section-counts"
            >
              <span>{generatedCounts[tab.id]}</span>
              <small>{publishedPrivateCounts[tab.id]}</small>
              <small className="public-count">{publishedPublicCounts[tab.id]}</small>
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
            <h3 className="profile-panel-kicker">{activeLabel}</h3>
            <p>Generated items need review. Private items are active internally. Public items are managed in the preview.</p>
          </div>
          <span className="profile-review-panel-counts">
            {generatedCounts[activeTab]} Generated / {publishedPrivateCounts[activeTab]} Private / {publishedPublicCounts[activeTab]} Public
          </span>
        </div>
        <div className="profile-lifecycle-tabs" role="tablist" aria-label={`${activeLabel} lifecycle`}>
          <button
            aria-selected={effectiveLifecycle === "generated"}
            className={effectiveLifecycle === "generated" ? "active" : ""}
            onClick={() => onLifecycleChange("generated")}
            role="tab"
            type="button"
          >
            <span className="profile-lifecycle-label"><GeneratedIcon /> Generated</span>{" "}
            <small className="profile-lifecycle-count">{generatedCounts[activeTab]}</small>
          </button>
          <button
            aria-selected={effectiveLifecycle === "private"}
            className={effectiveLifecycle === "private" ? "active" : ""}
            onClick={() => onLifecycleChange("private")}
            role="tab"
            type="button"
          >
            <span className="profile-lifecycle-label">Private</span>{" "}
            <small className="profile-lifecycle-count">{publishedPrivateCounts[activeTab]}</small>
          </button>
          {showArchivedTab ? (
            <button
              aria-selected={effectiveLifecycle === "archived"}
              className={`archived-link-tab${effectiveLifecycle === "archived" ? " active" : ""}`}
              onClick={() => onLifecycleChange("archived")}
              role="tab"
              type="button"
            >
              Archived
            </button>
          ) : null}
        </div>
        <section className="profile-review-card" aria-label={`${lifecycleLabel(effectiveLifecycle)} ${activeLabel}`}>
          {fieldGroup ? (
            <FieldGroupPanel
              fields={fieldGroup === "profile_basics" ? profileFields?.profileBasics ?? [] : profileFields?.targets ?? []}
              lifecycle={effectiveLifecycle}
              onProfileFieldUpdate={onProfileFieldUpdate}
            />
          ) : effectiveLifecycle === "generated" ? (
            <ProfileReviewTabContent
              activeTab={activeTab}
              draft={draft}
              onDraftItemUpdate={onDraftItemUpdate}
            />
          ) : effectiveLifecycle === "private" ? (
            <PublishedProfileTabContent
              activeTab={activeTab}
              onEdit={onPublishedEdit}
              onPublishedItemUpdate={onPublishedItemUpdate}
              publishedProfile={publishedProfile}
              publicProfile={publicProfile}
            />
          ) : (
            <ArchivedProfileTabContent activeTab={activeTab} draft={draft} />
          )}
        </section>
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
  onDraftItemUpdate?: DraftItemUpdateHandler;
}) {
  if (activeTab === "basics") {
    return <EmptyMessage>Profile basics use field-level review rows.</EmptyMessage>;
  }

  if (activeTab === "targets") {
    return <EmptyMessage>Targets use field-level review rows.</EmptyMessage>;
  }

  if (!draft) {
    return <EmptyReviewList activeTab={activeTab} />;
  }

  if (activeTab === "experience") {
    const items = draft.experienceSummaries.filter(
      (item) => isPendingDraftItem(item) && (item.itemType === "experience" || item.itemType === "project")
    );
    return <ExperienceList emptyLabel="No generated experience or project items yet." items={items} onDraftItemUpdate={onDraftItemUpdate} showType />;
  }

  if (activeTab === "education") {
    return (
      <ExperienceList
        emptyLabel="No generated education items yet."
        items={draft.experienceSummaries.filter((item) => isPendingDraftItem(item) && item.itemType === "education")}
        onDraftItemUpdate={onDraftItemUpdate}
      />
    );
  }

  if (activeTab === "certifications") {
    return (
      <ExperienceList
        emptyLabel="No generated certification items yet."
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
          <li className="profile-review-item draft-review-card editable-review-card" key={skill.id}>
            <div className="profile-review-primary">
              <TitleWithBadges title={skill.skill}>
                <ItemIconSet item={skill} />
              </TitleWithBadges>
            </div>
            <div className="editable-card-grid">
              <EditableField label="Skill" onSave={(value) => onDraftItemUpdate?.("skill", skill.id, { skill: value })} value={skill.skill} />
              <EditableField label="Category" onSave={(value) => onDraftItemUpdate?.("skill", skill.id, { category: value })} value={skill.category} />
              <EditableField label="Years min" onSave={(value) => onDraftItemUpdate?.("skill", skill.id, { yearsMin: nullableNumber(value) })} value={formatOptionalNumber(skill.yearsMin)} />
              <EditableField label="Years max" onSave={(value) => onDraftItemUpdate?.("skill", skill.id, { yearsMax: nullableNumber(value) })} value={formatOptionalNumber(skill.yearsMax)} />
            </div>
            <EditableField
              className="full-span"
              label="Evidence"
              multiline
              onSave={(value) => onDraftItemUpdate?.("skill", skill.id, { evidence: value })}
              value={skill.evidence}
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
      <EmptyMessage>No generated skill claims yet.</EmptyMessage>
    );
  }

  if (activeTab === "achievements") {
    const achievements = draft.facts.filter((fact) => isPendingDraftItem(fact) && looksLikeAchievement(fact.claim, fact.category));
    return achievements.length ? <FactList facts={achievements} onDraftItemUpdate={onDraftItemUpdate} /> : <EmptyMessage>No generated achievement or outcome items yet.</EmptyMessage>;
  }

  if (activeTab === "facts") {
    const facts = draft.facts.filter(isPendingDraftItem);
    return facts.length ? <FactList facts={facts} onDraftItemUpdate={onDraftItemUpdate} /> : <EmptyMessage>No generated facts or claims yet.</EmptyMessage>;
  }

  const links = draft.links.filter(isPendingDraftItem);
  return links.length ? (
    <ul className="profile-review-list">
      {links.map((link) => (
        <li className="profile-review-item draft-review-card editable-review-card" key={link.id}>
          <div className="profile-review-primary">
            <TitleWithBadges title={link.label}>
              <ItemIconSet item={link} />
            </TitleWithBadges>
          </div>
          <div className="editable-card-grid">
            <EditableField label="Label" onSave={(value) => onDraftItemUpdate?.("evidence", link.id, { label: value })} value={link.label} />
            <EditableField label="URL" onSave={(value) => onDraftItemUpdate?.("evidence", link.id, { url: value })} value={link.url} />
          </div>
          <ReviewActions item={link} itemType="evidence" onDraftItemUpdate={onDraftItemUpdate} />
        </li>
      ))}
    </ul>
  ) : (
    <EmptyMessage>No generated evidence links yet.</EmptyMessage>
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
  onDraftItemUpdate?: DraftItemUpdateHandler;
  showType?: boolean;
}) {
  if (!items.length) {
    return <EmptyMessage>{emptyLabel}</EmptyMessage>;
  }

  return (
    <ul className="profile-review-list">
      {items.map((experience) => (
        <li className="profile-review-item draft-review-card editable-review-card" key={experience.id}>
          <div className="profile-review-primary">
            <TitleWithBadges title={experience.title}>
              <ItemIconSet item={experience} />
            </TitleWithBadges>
          </div>
          <div className="editable-card-grid">
            <EditableField label="Title" onSave={(value) => onDraftItemUpdate?.("experience", experience.id, { title: value })} value={experience.title} />
            <EditableField label="Organization" onSave={(value) => onDraftItemUpdate?.("experience", experience.id, { organization: value })} value={experience.organization} />
            <EditableField label="From" onSave={(value) => onDraftItemUpdate?.("experience", experience.id, { startDate: value })} value={experience.startDate} />
            <EditableField label="To" onSave={(value) => onDraftItemUpdate?.("experience", experience.id, { endDate: value })} value={experience.endDate} />
            <EditableField label="Location" onSave={(value) => onDraftItemUpdate?.("experience", experience.id, { location: value })} value={experience.location} />
          </div>
          <EditableField
            className="full-span"
            label="Summary"
            multiline
            onSave={(value) => onDraftItemUpdate?.("experience", experience.id, { summary: value })}
            value={experience.summary}
          />
          <EditableField
            className="full-span"
            label="Bullets"
            multiline
            onSave={(value) => onDraftItemUpdate?.("experience", experience.id, { bullets: splitLines(value) })}
            value={experience.bullets.join("\n")}
          />
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
  onDraftItemUpdate?: DraftItemUpdateHandler;
}) {
  return (
    <ul className="profile-review-list">
      {facts.map((fact) => (
        <EditableFactRow fact={fact} key={fact.id} onDraftItemUpdate={onDraftItemUpdate} />
      ))}
    </ul>
  );
}

function ArchivedProfileTabContent({ activeTab, draft }: { activeTab: ReviewTabId; draft: MockProfileDraft | null }) {
  if (!draft) {
    return <EmptyReviewList activeTab={activeTab} />;
  }
  if (activeTab === "basics" || activeTab === "targets") {
    return <EmptyMessage>No archived {reviewTabs.find((tab) => tab.id === activeTab)?.label.toLowerCase()} yet.</EmptyMessage>;
  }
  if (activeTab === "skills") {
    const skills = draft.skillClaims.filter(isArchivedDraftItem);
    return skills.length ? (
      <ul className="profile-review-list">
        {skills.map((skill) => (
          <li className="profile-review-item" key={skill.id}>
            <TitleWithBadges title={skill.skill}>
              <ItemIconSet item={skill} />
            </TitleWithBadges>
            <p>{skill.evidence || skill.category}</p>
          </li>
        ))}
      </ul>
    ) : <EmptyMessage>No archived skills yet.</EmptyMessage>;
  }
  if (activeTab === "experience" || activeTab === "education" || activeTab === "certifications") {
    const itemTypes =
      activeTab === "experience" ? ["experience", "project"] : activeTab === "education" ? ["education"] : ["certification"];
    const items = draft.experienceSummaries.filter((item) => isArchivedDraftItem(item) && itemTypes.includes(item.itemType));
    return items.length ? (
      <ul className="profile-review-list">
        {items.map((item) => (
          <li className="profile-review-item" key={item.id}>
            <TitleWithBadges title={item.title}>
              <ItemIconSet item={item} />
            </TitleWithBadges>
            <p>{item.summary}</p>
          </li>
        ))}
      </ul>
    ) : <EmptyMessage>No archived {reviewTabs.find((tab) => tab.id === activeTab)?.label.toLowerCase()} yet.</EmptyMessage>;
  }
  if (activeTab === "evidence") {
    const links = draft.links.filter(isArchivedDraftItem);
    return links.length ? (
      <ul className="profile-review-list">
        {links.map((link) => (
          <li className="profile-review-item" key={link.id}>
            <TitleWithBadges title={link.label}>
              <ItemIconSet item={link} />
            </TitleWithBadges>
            <a href={link.url} rel="noreferrer" target="_blank">{link.url}</a>
          </li>
        ))}
      </ul>
    ) : <EmptyMessage>No archived evidence links yet.</EmptyMessage>;
  }
  const facts = draft.facts.filter((fact) =>
    isArchivedDraftItem(fact) && (activeTab === "achievements" ? looksLikeAchievement(fact.claim, fact.category) : true)
  );
  return facts.length ? (
    <ul className="profile-review-list">
      {facts.map((fact) => (
        <li className="profile-review-item" key={fact.id}>
          <TitleWithBadges title={fact.category}>
            <ItemIconSet item={fact} />
          </TitleWithBadges>
          <p>{fact.claim}</p>
        </li>
      ))}
    </ul>
  ) : <EmptyMessage>No archived {activeTab === "achievements" ? "achievements" : "facts"} yet.</EmptyMessage>;
}

function PublishedProfileTabContent({
  activeTab,
  onEdit,
  onPublishedItemUpdate,
  publishedProfile,
  publicProfile
}: {
  activeTab: ReviewTabId;
  onEdit?: () => void;
  onPublishedItemUpdate?: PublishedItemUpdateHandler;
  publishedProfile?: PublishedProfileSnapshot | null;
  publicProfile?: PublicProfileSnapshot | null;
}) {
  const profile = publishedProfile ?? publicProfile;
  if (!profile) {
    return <EmptyMessage>No published profile loaded yet.</EmptyMessage>;
  }

  if (activeTab === "skills") {
    const skills = (profile.skillClaims ?? []).filter((skill) => skill.visibility === "private");
    return skills.length ? (
      <ul className="profile-review-list">
        {skills.map((skill) => (
          <li className="profile-review-item editable-review-card" key={skill.id}>
            <TitleWithBadges title={skill.skill}>
              <VisibilityTextBadge visibility={skill.visibility} />
            </TitleWithBadges>
            <div className="editable-card-grid">
              <EditableField label="Skill" onSave={(value) => onPublishedItemUpdate?.("skill", skill.id, { skill: value })} value={skill.skill} />
              <EditableField label="Category" onSave={(value) => onPublishedItemUpdate?.("skill", skill.id, { category: value })} value={skill.category} />
            </div>
            <EditableField
              className="full-span"
              label="Evidence"
              multiline
              onSave={(value) => onPublishedItemUpdate?.("skill", skill.id, { evidence: value })}
              value={skill.evidence ?? ""}
            />
            <PublishedActions itemId={skill.id} itemType="skill" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={skill.visibility} />
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No private skills yet.</EmptyMessage>
    );
  }

  if (activeTab === "experience" || activeTab === "education" || activeTab === "certifications") {
    const itemTypes =
      activeTab === "experience" ? ["experience", "project"] : activeTab === "education" ? ["education"] : ["certification"];
    const items = (profile.experienceAndProjects ?? []).filter((item) => itemTypes.includes(item.itemType || "experience") && item.visibility === "private");
    return items.length ? (
      <ul className="profile-review-list">
        {items.map((item) => (
          <li className="profile-review-item editable-review-card" key={item.id}>
            <TitleWithBadges title={item.title}>
              <VisibilityTextBadge visibility={item.visibility} />
            </TitleWithBadges>
            <div className="editable-card-grid">
              <EditableField label="Title" onSave={(value) => onPublishedItemUpdate?.("experience", item.id, { title: value })} value={item.title} />
              <EditableField label="Organization" onSave={(value) => onPublishedItemUpdate?.("experience", item.id, { organization: value })} value={item.organization ?? ""} />
              <EditableField label="From" onSave={(value) => onPublishedItemUpdate?.("experience", item.id, { startDate: value })} value={item.startDate ?? ""} />
              <EditableField label="To" onSave={(value) => onPublishedItemUpdate?.("experience", item.id, { endDate: value })} value={item.endDate ?? ""} />
              <EditableField label="Location" onSave={(value) => onPublishedItemUpdate?.("experience", item.id, { location: value })} value={item.location ?? ""} />
            </div>
            <EditableField
              className="full-span"
              label="Summary"
              multiline
              onSave={(value) => onPublishedItemUpdate?.("experience", item.id, { summary: value })}
              value={item.summary}
            />
            <EditableField
              className="full-span"
              label="Bullets"
              multiline
              onSave={(value) => onPublishedItemUpdate?.("experience", item.id, { bullets: splitLines(value) })}
              value={(item.bullets ?? []).join("\n")}
            />
            <PublishedActions itemId={item.id} itemType="experience" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={item.visibility} />
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No private {reviewTabs.find((tab) => tab.id === activeTab)?.label.toLowerCase()} yet.</EmptyMessage>
    );
  }

  if (activeTab === "evidence") {
    const links = (profile.evidenceLinks ?? []).filter((link) => link.visibility === "private");
    return links.length ? (
      <ul className="profile-review-list">
        {links.map((link) => (
          <li className="profile-review-item editable-review-card" key={link.id}>
            <TitleWithBadges title={link.label}>
              <VisibilityTextBadge visibility={link.visibility} />
            </TitleWithBadges>
            <div className="editable-card-grid">
              <EditableField label="Label" onSave={(value) => onPublishedItemUpdate?.("evidence", link.id, { label: value })} value={link.label} />
              <EditableField label="URL" onSave={(value) => onPublishedItemUpdate?.("evidence", link.id, { url: value })} value={link.url} />
            </div>
            <PublishedActions itemId={link.id} itemType="evidence" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={link.visibility} />
          </li>
        ))}
      </ul>
    ) : (
      <EmptyMessage>No private evidence links yet.</EmptyMessage>
    );
  }

  const facts = (profile.facts ?? []).filter((fact) =>
    fact.visibility === "private" && (activeTab === "achievements" ? looksLikeAchievement(fact.claim, fact.category) : true)
  );
  return facts.length ? (
    <ul className="profile-review-list">
      {facts.map((fact) => (
        <li className="profile-review-item editable-review-card" key={fact.id}>
          <TitleWithBadges title={fact.category}>
            <VisibilityTextBadge visibility={fact.visibility} />
          </TitleWithBadges>
          <EditableField
            className="full-span"
            label="Claim"
            multiline
            onSave={(value) => onPublishedItemUpdate?.("fact", fact.id, { claim: value })}
            value={fact.claim}
          />
          <EditableField label="Category" onSave={(value) => onPublishedItemUpdate?.("fact", fact.id, { category: value })} value={fact.category} />
          <PublishedActions itemId={fact.id} itemType="fact" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={fact.visibility} />
        </li>
      ))}
    </ul>
  ) : (
    <EmptyMessage>No private {activeTab === "achievements" ? "achievements" : "facts"} yet.</EmptyMessage>
  );
}

export function PublicPortfolioPreview({
  onEdit,
  onProfileFieldUpdate,
  onPublishedItemUpdate,
  publicPortfolioPath,
  publicProfile,
  publishedPublicItemCount
}: {
  onEdit?: () => void;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
  onPublishedItemUpdate?: PublishedItemUpdateHandler;
  publicPortfolioPath: string | null;
  publicProfile: PublicProfileSnapshot | null;
  publishedPublicItemCount: number;
}) {
  const previewPath = publicPortfolioPath || "/portfolio";
  const facts = (publicProfile?.facts ?? []).filter((fact) => fact.visibility === "public" && fact.verificationStatus === "published");
  const skills = (publicProfile?.skillClaims ?? []).filter(
    (skill) => skill.visibility === "public" && skill.publicationStatus === "published" && skill.verificationStatus === "published"
  );
  const experience = (publicProfile?.experienceAndProjects ?? []).filter(
    (item) => item.visibility === "public" && item.publicationStatus === "published"
  );
  const links = (publicProfile?.evidenceLinks ?? []).filter((link) => link.visibility === "public" && link.publicationStatus === "published");
  const selectedWork = experience.filter((item) => item.itemType === "experience" || item.itemType === "project");
  const education = experience.filter((item) => item.itemType === "education");
  const certifications = experience.filter((item) => item.itemType === "certification");
  const achievements = facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category));
  const publicBasics = publicFieldEntries(publicProfile?.profileFields?.profileBasics, publicProfileBasicPreviewLabels);
  const publicTargets = publicFieldEntries(publicProfile?.profileFields?.targets, publicTargetPreviewLabels);
  const publicContactFields = publicBasics.filter((field) => !["displayName", "headline", "summary"].includes(field.name));
  const displayNameField = publicFieldEntry(publicProfile?.profileFields?.profileBasics, "displayName", "Name");
  const headlineField = publicFieldEntry(publicProfile?.profileFields?.profileBasics, "headline", "Headline");
  const summaryField = publicFieldEntry(publicProfile?.profileFields?.profileBasics, "summary", "Summary");
  const hasProfileDetails = Boolean(education.length || certifications.length || links.length || publicContactFields.length);
  const hasProofRail = Boolean(skills.length || achievements.length);
  const hasPublicContent = Boolean(
    facts.length || skills.length || experience.length || links.length || publicBasics.length || publicTargets.length
  );

  return (
    <section className="profile-side-card public-preview-card">
      <div className="profile-side-card-header">
        <div>
          <p className="eyebrow">Public portfolio preview</p>
          <h3>Manage public profile items</h3>
        </div>
        <a href={previewPath}>Open</a>
      </div>
      {hasPublicContent ? (
        <div className="admin-portfolio-preview portfolio-page">
          <section className={`portfolio-hero admin-portfolio-hero${hasProfileDetails ? "" : " solo"}`}>
            <div className="portfolio-hero-copy">
              <p className="eyebrow">JobOps candidate-agent portfolio</p>
              <AdminPreviewHeroField
                field={displayNameField}
                fallback={publicProfile?.displayName || "Published portfolio"}
                fieldName="displayName"
                onEdit={onEdit}
                onProfileFieldUpdate={onProfileFieldUpdate}
                variant="title"
              />
              {publicProfile?.headline ? (
                <AdminPreviewHeroField
                  field={headlineField}
                  fallback={publicProfile.headline}
                  fieldName="headline"
                  onEdit={onEdit}
                  onProfileFieldUpdate={onProfileFieldUpdate}
                  variant="lede"
                />
              ) : null}
              {publicProfile?.summary ? (
                <AdminPreviewHeroField
                  field={summaryField}
                  fallback={publicProfile.summary}
                  fieldName="summary"
                  onEdit={onEdit}
                  onProfileFieldUpdate={onProfileFieldUpdate}
                  variant="summary"
                />
              ) : null}
            </div>
            {hasProfileDetails ? (
              <aside className="portfolio-verification-panel" aria-label="Public profile details">
                <div className="portfolio-panel-header">
                  <h2>Education, credentials, and contact.</h2>
                </div>
                {education.length ? <AdminPreviewDetailList items={education} onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} title="Education" /> : null}
                {certifications.length ? (
                  <AdminPreviewDetailList items={certifications} onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} scroll title="Certifications" />
                ) : null}
                {publicContactFields.length ? (
                  <AdminPreviewContactFieldList fields={publicContactFields} onEdit={onEdit} onProfileFieldUpdate={onProfileFieldUpdate} title="Contact details" />
                ) : null}
                {links.length ? <AdminPreviewLinkList links={links} onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} title="Contact & URLs" /> : null}
              </aside>
            ) : null}
          </section>
          {publicTargets.length ? (
            <section className="content-band portfolio-section">
              <p className="section-kicker">Role intent</p>
              <h2>Target direction</h2>
              <div className="portfolio-role-intent-grid">
              {publicTargets.map((field) => (
                <article className="portfolio-role-intent-group admin-preview-item" key={`targets-${field.name}`}>
                  <h3>{field.label}</h3>
                  {field.name === "targetTitles" || field.name === "roleFamilies" || field.name === "preferredLocations" || field.name === "preferredWorkMode" ? (
                    <ChipList items={splitPreviewList(field.value)} />
                  ) : (
                    <p>{field.value}</p>
                  )}
                  <AdminPreviewFieldControls
                    fieldGroup="targets"
                    fieldName={field.name}
                    onEdit={onEdit}
                    onProfileFieldUpdate={onProfileFieldUpdate}
                  />
                </article>
              ))}
              </div>
            </section>
          ) : null}
          {facts.length ? (
            <section className="portfolio-facts-band" id="profile-facts">
              <div>
                <p className="section-kicker">Approved facts</p>
                <h2>Public, published information only</h2>
              </div>
              <div className="portfolio-fact-callouts">
              {facts.slice(0, 6).map((fact) => (
                <article className="portfolio-fact-callout admin-preview-item" key={fact.id}>
                  <p>{fact.claim}</p>
                  <span>{fact.category}</span>
                  <AdminPreviewControls
                    itemId={fact.id}
                    itemType="fact"
                    onEdit={onEdit}
                    onPublishedItemUpdate={onPublishedItemUpdate}
                    visibility={fact.visibility}
                  />
                </article>
              ))}
              </div>
            </section>
          ) : null}
          {selectedWork.length || hasProofRail ? (
            <section className="portfolio-evidence-layout">
              {selectedWork.length ? (
                <div className="portfolio-work-column">
                  <p className="section-kicker">Selected work</p>
                  <h2>Featured projects and experience</h2>
                  <div className="portfolio-timeline">
                    {selectedWork.slice(0, 8).map((item) => (
                      <article className="portfolio-card admin-preview-item" key={item.id}>
                        <p className="section-kicker">{item.itemType}</p>
                        <h3>{item.title}</h3>
                        {item.organization ? <p>{item.organization}</p> : null}
                        {item.startDate || item.endDate || item.location ? (
                          <p className="portfolio-meta">{[joinDates(item.startDate, item.endDate), item.location].filter(Boolean).join(" - ")}</p>
                        ) : null}
                        <p>{item.summary}</p>
                        {item.bullets?.length ? (
                          <ul>
                            {item.bullets.slice(0, 3).map((bullet) => (
                              <li key={bullet}>{bullet}</li>
                            ))}
                          </ul>
                        ) : null}
                        <AdminPreviewControls itemId={item.id} itemType="experience" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={item.visibility} />
                      </article>
                    ))}
                  </div>
                </div>
              ) : null}

              {hasProofRail ? (
                <aside className="portfolio-proof-rail" aria-label="Skills and achievements">
                  {skills.length ? (
                    <section className="portfolio-rail-section">
                      <p className="section-kicker">Skills</p>
                      <h2>Skills with approved evidence</h2>
                      <div className="portfolio-skill-stack">
                        {skills.slice(0, 12).map((skill) => (
                          <article className="portfolio-card admin-preview-item" key={skill.id}>
                            <h3>{skill.skill}</h3>
                            <p>{skill.evidence || skill.category}</p>
                            <AdminPreviewControls itemId={skill.id} itemType="skill" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={skill.visibility} />
                          </article>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {achievements.length ? (
                    <section className="portfolio-rail-section">
                      <p className="section-kicker">Achievements</p>
                      <h2>Selected proof points</h2>
                      <ul className="portfolio-achievement-list">
                        {achievements.slice(0, 8).map((fact) => (
                          <li className="admin-preview-item" key={fact.id}>
                            {fact.claim}
                            <AdminPreviewControls itemId={fact.id} itemType="fact" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={fact.visibility} />
                          </li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                </aside>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : (
        <EmptyMessage>No public published profile items yet.</EmptyMessage>
      )}
      <p className="profile-lifecycle-note">
        This preview uses only the publicProfile payload from the public serializer. Published public item
        count: {publishedPublicItemCount}.
      </p>
    </section>
  );
}

function AdminPreviewHeroField({
  fallback,
  field,
  fieldName,
  onEdit,
  onProfileFieldUpdate,
  variant
}: {
  fallback: string;
  field: { label: string; name: string; value: string } | null;
  fieldName: string;
  onEdit?: () => void;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
  variant: "title" | "lede" | "summary";
}) {
  const content = field?.value || fallback;
  const controls = field ? (
    <AdminPreviewFieldControls
      fieldGroup="profile_basics"
      fieldName={fieldName}
      onEdit={onEdit}
      onProfileFieldUpdate={onProfileFieldUpdate}
    />
  ) : null;

  if (variant === "title") {
    return (
      <div className="admin-preview-hero-field">
        {field ? <span className="visually-hidden">{field.label}</span> : null}
        <h2>{content}</h2>
        {controls}
      </div>
    );
  }

  if (variant === "summary") {
    return (
      <div className="admin-preview-hero-field">
        {field ? <span className="visually-hidden">{field.label}</span> : null}
        <p className="portfolio-summary">{content}</p>
        {controls}
      </div>
    );
  }

  return (
    <div className="admin-preview-hero-field">
      {field ? <span className="visually-hidden">{field.label}</span> : null}
      <p className="lede">{content}</p>
      {controls}
    </div>
  );
}

function AdminPreviewDetailList({
  items,
  onEdit,
  onPublishedItemUpdate,
  scroll = false,
  title
}: {
  items: NonNullable<PublicProfileSnapshot["experienceAndProjects"]>;
  onEdit?: () => void;
  onPublishedItemUpdate?: PublishedItemUpdateHandler;
  scroll?: boolean;
  title: string;
}) {
  return (
    <div className={`portfolio-panel-block${scroll ? " scrollable" : ""}`}>
      <p className="section-kicker">{title}</p>
      <ul className="portfolio-detail-list">
        {items.map((item) => (
          <li className="admin-preview-item compact" key={item.id}>
            <strong>{item.title}</strong>
            {item.organization ? <span>{item.organization}</span> : null}
            {item.endDate || item.location ? <small>{[item.endDate, item.location].filter(Boolean).join(" - ")}</small> : null}
            <AdminPreviewControls itemId={item.id} itemType="experience" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={item.visibility} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function AdminPreviewContactFieldList({
  fields,
  onEdit,
  onProfileFieldUpdate,
  title
}: {
  fields: Array<{ label: string; name: string; value: string }>;
  onEdit?: () => void;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
  title: string;
}) {
  return (
    <div className="portfolio-panel-block">
      <p className="section-kicker">{title}</p>
      <ul className="portfolio-detail-list">
        {fields.map((field) => (
          <li className="admin-preview-item compact" key={`profile_basics-${field.name}`}>
            <strong>{field.label}</strong>
            <span>{field.value}</span>
            <AdminPreviewFieldControls fieldGroup="profile_basics" fieldName={field.name} onEdit={onEdit} onProfileFieldUpdate={onProfileFieldUpdate} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function AdminPreviewLinkList({
  links,
  onEdit,
  onPublishedItemUpdate,
  title
}: {
  links: NonNullable<PublicProfileSnapshot["evidenceLinks"]>;
  onEdit?: () => void;
  onPublishedItemUpdate?: PublishedItemUpdateHandler;
  title: string;
}) {
  return (
    <div className="portfolio-panel-block">
      <p className="section-kicker">{title}</p>
      <ul className="portfolio-mini-link-list">
        {links.map((link) => (
          <li className="admin-preview-item compact" key={link.id}>
            <a href={link.url} rel="noreferrer" target="_blank">{link.label || link.url}</a>
            <AdminPreviewControls itemId={link.id} itemType="evidence" onEdit={onEdit} onPublishedItemUpdate={onPublishedItemUpdate} visibility={link.visibility} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChipList({ items }: { items: string[] }) {
  if (!items.length) {
    return null;
  }
  return (
    <div className="portfolio-chip-list">
      {items.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
  );
}

function publicFieldEntries(values: Record<string, string> | undefined, labels: Record<string, string>) {
  if (!values) {
    return [];
  }
  return Object.entries(labels)
    .map(([name, label]) => ({ label, name, value: values[name] ?? "" }))
    .filter((field) => field.value.trim().length > 0);
}

function publicFieldEntry(values: Record<string, string> | undefined, name: string, label: string) {
  const value = values?.[name] ?? "";
  return value.trim().length ? { label, name, value } : null;
}

function splitPreviewList(value: string) {
  return value.split(/[;\n,]/).map((item) => item.trim()).filter(Boolean);
}

function joinDates(start?: string | null, end?: string | null) {
  if (start && end) {
    return `${start} - ${end}`;
  }
  return start || end || "";
}

function AdminPreviewControls({
  itemId,
  itemType,
  onEdit,
  onPublishedItemUpdate,
  showArchive = true,
  visibility
}: {
  itemId: string;
  itemType: ProfileItemType;
  onEdit?: () => void;
  onPublishedItemUpdate?: PublishedItemUpdateHandler;
  showArchive?: boolean;
  visibility: "private" | "public";
}) {
  const canArchive = showArchive;
  return (
    <div className="admin-preview-controls" aria-label="Public preview admin controls">
      <button
        className="button-action"
        disabled={!onPublishedItemUpdate || visibility === "private"}
        onClick={() => onPublishedItemUpdate?.(itemType, itemId, { visibility: "private" })}
        type="button"
      >
        Make private
      </button>
      <button className="button-action" disabled={!onEdit} onClick={onEdit} type="button">
        Edit
      </button>
      {canArchive ? (
        <button
          className="button-action subtle-danger"
          disabled={!onPublishedItemUpdate}
          onClick={() => onPublishedItemUpdate?.(itemType, itemId, { archive: true })}
          type="button"
        >
          Archive
        </button>
      ) : null}
    </div>
  );
}

function AdminPreviewFieldControls({
  fieldGroup,
  fieldName,
  onEdit,
  onProfileFieldUpdate
}: {
  fieldGroup: ProfileFieldState["group"];
  fieldName: string;
  onEdit?: () => void;
  onProfileFieldUpdate?: ProfileFieldUpdateHandler;
}) {
  return (
    <div className="admin-preview-controls" aria-label="Public field preview admin controls">
      <button
        className="button-action"
        disabled={!onProfileFieldUpdate}
        onClick={() => onProfileFieldUpdate?.(fieldGroup, fieldName, { visibility: "private" })}
        type="button"
      >
        Make private
      </button>
      <button className="button-action" disabled={!onEdit} onClick={onEdit} type="button">
        Edit
      </button>
      <button
        className="button-action subtle-danger"
        disabled={!onProfileFieldUpdate}
        onClick={() => onProfileFieldUpdate?.(fieldGroup, fieldName, { archive: true, lifecycleStatus: "published" })}
        type="button"
      >
        Archive
      </button>
    </div>
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
  return <span className={`visibility-text-badge ${visibility}`}>{visibility === "public" ? "Public" : "Private"}</span>;
}

type AutosaveStatus = "idle" | "saving" | "saved" | "error";

function EditableField({
  className,
  label,
  multiline = false,
  onSave,
  value
}: {
  className?: string;
  label: string;
  multiline?: boolean;
  onSave?: (value: string) => Promise<boolean> | boolean | void;
  value: string;
}) {
  const [draftValue, setDraftValue] = useState(value);
  const [status, setStatus] = useState<AutosaveStatus>("idle");
  const baseline = useRef(value);
  const inFlightValue = useRef<string | null>(null);

  useEffect(() => {
    baseline.current = value;
    setDraftValue(value);
    setStatus("idle");
  }, [value]);

  async function saveIfChanged() {
    if (!onSave || draftValue === baseline.current || inFlightValue.current === draftValue) {
      return;
    }
    const valueToSave = draftValue;
    inFlightValue.current = valueToSave;
    setStatus("saving");
    try {
      const result = await onSave(valueToSave);
      if (result === false) {
        setStatus("error");
        return;
      }
      baseline.current = valueToSave;
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      if (inFlightValue.current === valueToSave) {
        inFlightValue.current = null;
      }
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (!multiline && event.key === "Enter") {
      event.preventDefault();
      void saveIfChanged();
      return;
    }
    if (multiline && event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void saveIfChanged();
    }
  }

  const fieldProps = {
    onBlur: () => void saveIfChanged(),
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setDraftValue(event.target.value);
      setStatus("idle");
    },
    onKeyDown: handleKeyDown,
    value: draftValue
  };

  return (
    <label className={className}>
      <span className="editable-field-label">
        {label}
        <SaveStatus status={status} />
      </span>
      {multiline ? <textarea className="small-textarea" {...fieldProps} /> : <input {...fieldProps} />}
    </label>
  );
}

function CompactEditableField({
  label,
  multiline = false,
  onSave,
  value
}: {
  label: string;
  multiline?: boolean;
  onSave?: (value: string) => Promise<boolean> | boolean | void;
  value: string;
}) {
  const inputId = useId();
  const [draftValue, setDraftValue] = useState(value);
  const [status, setStatus] = useState<AutosaveStatus>("idle");
  const baseline = useRef(value);
  const inFlightValue = useRef<string | null>(null);

  useEffect(() => {
    baseline.current = value;
    setDraftValue(value);
    setStatus("idle");
  }, [value]);

  async function saveIfChanged() {
    if (!onSave || draftValue === baseline.current || inFlightValue.current === draftValue) {
      return;
    }
    const valueToSave = draftValue;
    inFlightValue.current = valueToSave;
    setStatus("saving");
    try {
      const result = await onSave(valueToSave);
      if (result === false) {
        setStatus("error");
        return;
      }
      baseline.current = valueToSave;
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      if (inFlightValue.current === valueToSave) {
        inFlightValue.current = null;
      }
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (!multiline && event.key === "Enter") {
      event.preventDefault();
      void saveIfChanged();
      return;
    }
    if (multiline && event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void saveIfChanged();
    }
  }

  const fieldProps = {
    "aria-label": label,
    id: inputId,
    onBlur: () => void saveIfChanged(),
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setDraftValue(event.target.value);
      setStatus("idle");
    },
    onKeyDown: handleKeyDown,
    value: draftValue
  };

  return (
    <div className="compact-field-editor">
      <label className="visually-hidden" htmlFor={inputId}>{label}</label>
      {multiline ? <textarea className="small-textarea" {...fieldProps} /> : <input {...fieldProps} />}
      <SaveStatus status={status} />
    </div>
  );
}

function SaveStatus({ status }: { status: AutosaveStatus }) {
  if (status === "idle") {
    return null;
  }
  return <small className={`autosave-status ${status}`}>{status === "saving" ? "Saving..." : status === "saved" ? "Saved" : "Save failed"}</small>;
}

function EditableFactRow({
  fact,
  onDraftItemUpdate
}: {
  fact: MockProfileDraft["facts"][number];
  onDraftItemUpdate?: DraftItemUpdateHandler;
}) {
  return (
    <li className="profile-review-item fact-edit-row draft-review-card editable-review-card">
      <div className="profile-review-primary">
        <TitleWithBadges title={fact.category}>
          <ItemIconSet item={fact} />
        </TitleWithBadges>
      </div>
      <EditableField
        className="full-span"
        label="Claim"
        multiline
        onSave={(value) => onDraftItemUpdate?.("fact", fact.id, { claim: value })}
        value={fact.claim}
      />
      <EditableField label="Category" onSave={(value) => onDraftItemUpdate?.("fact", fact.id, { category: value })} value={fact.category} />
      <div className="review-action-row">
        <ReviewActions item={fact} itemType="fact" onDraftItemUpdate={onDraftItemUpdate} />
      </div>
    </li>
  );
}

function ReviewActions({
  item,
  itemType,
  onDraftItemUpdate,
  showArchive = true
}: {
  item: BadgeableDraftItem & { id: string };
  itemType: ProfileItemType;
  onDraftItemUpdate?: DraftItemUpdateHandler;
  showArchive?: boolean;
}) {
  const canArchive = showArchive;
  return (
    <div className="review-action-row">
      <button
        className="secondary-action button-action"
        disabled={!onDraftItemUpdate || item.published}
        onClick={() => onDraftItemUpdate?.(itemType, item.id, { publishVisibility: "private" })}
        type="button"
      >
        Publish private
      </button>
      <button
        className="secondary-action button-action"
        disabled={!onDraftItemUpdate || item.published}
        onClick={() => onDraftItemUpdate?.(itemType, item.id, { publishVisibility: "public" })}
        type="button"
      >
        Publish public
      </button>
      {canArchive ? (
        <button
          className="secondary-action button-action subtle-danger"
          disabled={!onDraftItemUpdate || item.published}
          onClick={() => onDraftItemUpdate?.(itemType, item.id, { reviewStatus: "rejected", visibility: "private" })}
          type="button"
        >
          Archive
        </button>
      ) : null}
    </div>
  );
}

function PublishedActions({
  itemId,
  itemType,
  onEdit,
  onPublishedItemUpdate,
  visibility,
  showArchive = true
}: {
  itemId: string;
  itemType: ProfileItemType;
  onEdit?: () => void;
  onPublishedItemUpdate?: PublishedItemUpdateHandler;
  showArchive?: boolean;
  visibility: "private" | "public";
}) {
  const canArchive = showArchive;
  return (
    <div className="review-action-row published-action-row">
      {visibility === "public" ? (
        <button
          className="secondary-action button-action"
          disabled={!onPublishedItemUpdate}
          onClick={() => onPublishedItemUpdate?.(itemType, itemId, { visibility: "private" })}
          type="button"
        >
          Make private
        </button>
      ) : null}
      {visibility === "private" ? (
        <button
          className="secondary-action button-action"
          disabled={!onPublishedItemUpdate}
          onClick={() => onPublishedItemUpdate?.(itemType, itemId, { visibility: "public" })}
          type="button"
        >
          Make public
        </button>
      ) : null}
      <button
        className="secondary-action button-action"
        disabled={!onEdit}
        onClick={onEdit}
        type="button"
      >
        Edit
      </button>
      {canArchive ? (
        <button
          className="secondary-action button-action subtle-danger"
          disabled={!onPublishedItemUpdate}
          onClick={() => onPublishedItemUpdate?.(itemType, itemId, { archive: true })}
          type="button"
        >
          Archive
        </button>
      ) : null}
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
  return <EmptyMessage>No generated {label} yet.</EmptyMessage>;
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

function buildPublishedReviewCounts(
  publishedProfile?: PublishedProfileSnapshot | null,
  visibility?: "private" | "public"
): Record<ReviewTabId, number> {
  const facts = (publishedProfile?.facts ?? []).filter((item) => !visibility || item.visibility === visibility);
  const experience = (publishedProfile?.experienceAndProjects ?? []).filter((item) => !visibility || item.visibility === visibility);
  const counts = {
    basics: publishedProfile ? 1 : 0,
    targets: hasTargetRoleIntent(publishedProfile?.targetRoleIntent) && (!visibility || publishedProfile?.targetRoleIntent?.visibility === visibility) ? 1 : 0,
    experience: experience.filter((item) => (item.itemType || "experience") === "experience" || item.itemType === "project").length,
    skills: (publishedProfile?.skillClaims ?? []).filter((item) => !visibility || item.visibility === visibility).length,
    achievements: facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category)).length,
    facts: facts.length,
    evidence: (publishedProfile?.evidenceLinks ?? []).filter((item) => !visibility || item.visibility === visibility).length,
    education: experience.filter((item) => item.itemType === "education").length,
    certifications: experience.filter((item) => item.itemType === "certification").length
  };
  return counts;
}

function buildArchivedReviewCounts(draft: MockProfileDraft | null): Record<ReviewTabId, number> {
  const facts = draft?.facts.filter(isArchivedDraftItem) ?? [];
  const skills = draft?.skillClaims.filter(isArchivedDraftItem) ?? [];
  const experience = draft?.experienceSummaries.filter(isArchivedDraftItem) ?? [];
  const links = draft?.links.filter(isArchivedDraftItem) ?? [];
  return {
    basics: 0,
    targets: 0,
    experience: experience.filter((item) => item.itemType === "experience" || item.itemType === "project").length,
    skills: skills.length,
    achievements: facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category)).length,
    facts: facts.length,
    evidence: links.length,
    education: experience.filter((item) => item.itemType === "education").length,
    certifications: experience.filter((item) => item.itemType === "certification").length
  };
}

function buildFieldReviewCounts(profileFields?: ProfileFieldGroups | null): {
  generated: Partial<Record<ReviewTabId, number>>;
  published: Partial<Record<ReviewTabId, number>>;
  public: Partial<Record<ReviewTabId, number>>;
  archived: Partial<Record<ReviewTabId, number>>;
} {
  const basics = profileFields?.profileBasics ?? [];
  const targets = profileFields?.targets ?? [];
  return {
    generated: {
      basics: basics.filter((field) => field.generated).length,
      targets: targets.filter((field) => field.generated).length
    },
    published: {
      basics: basics.filter((field) => field.published?.visibility === "private").length,
      targets: targets.filter((field) => field.published?.visibility === "private").length
    },
    public: {
      basics: basics.filter((field) => field.published?.visibility === "public").length,
      targets: targets.filter((field) => field.published?.visibility === "public").length
    },
    archived: {
      basics: basics.reduce((count, field) => count + field.archived.filter(isDisplayableArchivedFieldValue).length, 0),
      targets: targets.reduce((count, field) => count + field.archived.filter(isDisplayableArchivedFieldValue).length, 0)
    }
  };
}

function lifecycleLabel(lifecycle: LifecycleTab) {
  return lifecycle === "generated" ? "Generated" : lifecycle === "private" ? "Private" : "Archived";
}

function totalDraftCount(draft: MockProfileDraft | null) {
  const counts = buildReviewCounts(draft);
  return reviewTabs.filter((tab) => tab.id !== "basics").reduce((sum, tab) => sum + counts[tab.id], 0);
}

function buildDraftActionMessage(patch: DraftItemPatch) {
  if (patch.publishVisibility === "public") {
    return "Generated item published public.";
  }
  if (patch.publishVisibility === "private") {
    return "Generated item published private.";
  }
  if (patch.reviewStatus === "rejected") {
    return "Generated item archived.";
  }
  return "Generated item updated.";
}

function buildPublishedActionMessage(patch: PublishedItemPatch) {
  if (patch.archive) {
    return "Published item archived.";
  }
  if (patch.visibility === "public") {
    return "Published item made public.";
  }
  if (patch.visibility === "private") {
    return "Published item made private.";
  }
  return "Published item saved.";
}

function buildProfileFieldActionMessage(patch: ProfileFieldPatch) {
  if (patch.archive) {
    return "Profile field archived.";
  }
  if (patch.publishVisibility === "public") {
    return "Profile field published public.";
  }
  if (patch.publishVisibility === "private") {
    return "Profile field published private.";
  }
  if (patch.visibility === "public") {
    return "Profile field made public.";
  }
  if (patch.visibility === "private") {
    return "Profile field made private.";
  }
  return "Profile field saved.";
}

function splitLines(value: string) {
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function nullableNumber(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const numeric = Number(trimmed);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatOptionalNumber(value?: number | null) {
  return typeof value === "number" ? String(value) : "";
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
      <LifecycleSourceIcon item={item} />
      <VisibilityIcon visibility={item.visibility} />
      {item.published ? <PublicationIcon published={item.published} /> : null}
    </span>
  );
}

function GeneratedIcon() {
  return (
    <svg className="generated-tab-icon" aria-hidden="true" viewBox="0 0 24 24">
      <rect x="6" y="8" width="12" height="9" rx="3" />
      <path d="M12 8V5" />
      <path d="M9.5 5h5" />
      <circle cx="10" cy="12" r=".7" />
      <circle cx="14" cy="12" r=".7" />
      <path d="M10 15h4" />
    </svg>
  );
}

function DraftIconSet({
  author,
  visibility
}: {
  author: "agent" | "user";
  visibility: BadgeableDraftItem["visibility"];
}) {
  return (
    <span className="icon-badge-row">
      <AuthorIcon author={author} />
      <VisibilityIcon visibility={visibility} />
    </span>
  );
}

function LifecycleSourceIcon({ item }: { item: BadgeableDraftItem }) {
  if (item.published) {
    return <IconBadge kind="published" label="Published" />;
  }
  if (item.status === "rejected") {
    return null;
  }

  return <IconBadge kind={item.status === "candidate_approved" ? "user" : "agent"} label={item.status === "candidate_approved" ? "Edited" : "Generated"} />;
}

function VisibilityIcon({ visibility }: { visibility: BadgeableDraftItem["visibility"] }) {
  return <IconBadge kind={visibility === "private" ? "private" : "public"} label={visibilityLabel(visibility)} />;
}

function PublicationIcon({ published }: { published: BadgeableDraftItem["published"] }) {
  return <IconBadge kind={published ? "published" : "unpublished"} label={published ? "Published" : "Generated"} />;
}

function AuthorIcon({ author }: { author: "agent" | "user" }) {
  return <IconBadge kind={author} label={author === "user" ? "Edited" : "Generated"} />;
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

function isPendingDraftItem(item: BadgeableDraftItem) {
  return !item.published && item.status !== "rejected";
}

function isArchivedDraftItem(item: BadgeableDraftItem) {
  return !item.published && item.status === "rejected";
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

function looksLikeAchievement(claim: string, category: string) {
  const normalized = `${claim} ${category}`.toLowerCase();
  return /%|\d|reduced|improved|increased|launched|shipped|built|deployed|optimized|scaled|throughput|hours|minutes/.test(
    normalized
  );
}
