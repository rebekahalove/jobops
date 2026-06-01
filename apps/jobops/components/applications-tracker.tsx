"use client";

import Link from "next/link";
import React, { useEffect, useMemo, useRef, useState } from "react";

export type ApplicationBucketId = "started" | "applied" | "in-process" | "archived";

const applicationTabs: Array<{ id: ApplicationBucketId; label: string }> = [
  { id: "started", label: "Started" },
  { id: "applied", label: "Applied" },
  { id: "in-process", label: "In Process" },
  { id: "archived", label: "Archived" }
];

export const applicationStatuses = [
  "saved",
  "started",
  "in_progress",
  "in_process",
  "applied",
  "interviewing",
  "rejected",
  "offer",
  "closed",
  "withdrawn"
] as const;

export type ApplicationStatus = (typeof applicationStatuses)[number];

export type ApplicationMaterialItem = {
  id: string;
  bundle_id: string;
  material_type: string;
  title: string;
  content: string;
  content_format: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type ApplicationMaterialBundle = {
  id: string;
  application_id: string;
  candidate_profile_id: string;
  status: string;
  model_provider: string | null;
  model_name: string | null;
  created_at: string;
  updated_at: string;
  items: ApplicationMaterialItem[];
};

export type TrackedApplication = {
  id: string;
  candidate_profile_id?: string;
  job_id?: string | null;
  saved_job_id?: string | null;
  company_id?: string | null;
  company_name: string;
  job_title: string;
  job_url: string | null;
  location: string | null;
  source: string | null;
  source_provider?: string | null;
  posting_date?: string | null;
  fit_summary?: string | null;
  salary_text?: string | null;
  remote_work_mode?: string | null;
  employment_type?: string | null;
  apply_url?: string | null;
  date_applied: string | null;
  status: ApplicationStatus;
  notes: string;
  next_follow_up_date: string | null;
  archived_at?: string | null;
  archived_reason?: string | null;
  archived_by_action?: string | null;
  created_at: string;
  updated_at: string;
  latest_material_bundle?: ApplicationMaterialBundle | null;
};

export function ApplicationsTracker({
  apiBasePath = "/api",
  workspaceBasePath = "",
  initialApplications = []
}: {
  apiBasePath?: string;
  workspaceBasePath?: string;
  initialApplications?: TrackedApplication[];
}) {
  const [applications, setApplications] = useState(initialApplications);
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<"success" | "error" | "info">("info");
  const [pendingApplicationId, setPendingApplicationId] = useState<string | null>(null);
  const [pendingArchiveApplicationId, setPendingArchiveApplicationId] = useState<string | null>(null);
  const [highlightedApplicationId, setHighlightedApplicationId] = useState<string | null>(null);
  const [activeBucket, setActiveBucket] = useState<ApplicationBucketId>(() => defaultApplicationBucket(initialApplications));
  const hasAppliedInitialBucket = useRef(initialApplications.length > 0);

  useEffect(() => {
    if (!message) {
      return;
    }
    const timeout = window.setTimeout(() => setMessage(""), messageKind === "error" ? 9000 : 5200);
    return () => window.clearTimeout(timeout);
  }, [message, messageKind]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const applicationId = new URLSearchParams(window.location.search).get("applicationId");
    if (applicationId) {
      setHighlightedApplicationId(applicationId);
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function loadApplications() {
      try {
        const response = await fetch(`${apiBasePath}/applications`, { cache: "no-store" });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          if (active) {
            setMessageKind("error");
            setMessage(apiErrorMessage(payload, response.status));
          }
          return;
        }
        if (!Array.isArray(payload)) {
          if (active) {
            setMessageKind("error");
            setMessage("Applications API returned an unexpected response.");
          }
          return;
        }
        if (active) {
          setMessage("");
          setApplications(payload);
          if (!hasAppliedInitialBucket.current) {
            setActiveBucket(defaultApplicationBucket(payload));
            hasAppliedInitialBucket.current = true;
          }
        }
      } catch {
        if (active) {
          setMessageKind("error");
          setMessage("Application API is unavailable. Start FastAPI to load saved records.");
        }
      }
    }

    loadApplications();
    window.addEventListener("jobops:applications-updated", loadApplications);
    return () => {
      active = false;
      window.removeEventListener("jobops:applications-updated", loadApplications);
    };
  }, [apiBasePath]);

  useEffect(() => {
    if (!highlightedApplicationId || typeof document === "undefined") {
      return;
    }
    const element = document.getElementById(applicationCardId(highlightedApplicationId));
    if (element) {
      element.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [highlightedApplicationId, applications]);

  const applicationCounts = useMemo(() => buildApplicationBucketCounts(applications), [applications]);
  const sortedApplications = useMemo(
    () => sortApplicationsForBucket(applications.filter((application) => applicationBucket(application) === activeBucket), activeBucket),
    [activeBucket, applications]
  );
  const activeEmptyState = applicationEmptyStates[activeBucket];

  async function markApplied(application: TrackedApplication) {
    setPendingApplicationId(application.id);
    setMessage("");

    try {
      const response = await fetch(`${apiBasePath}/applications/${application.id}/status`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ status: "applied" })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }

      setApplications((current) => current.map((item) => (item.id === application.id ? (payload as TrackedApplication) : item)));
      setHighlightedApplicationId(application.id);
      setMessageKind("success");
      setMessage("Application marked applied.");
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : "Could not mark application as applied.");
    } finally {
      setPendingApplicationId(null);
    }
  }

  async function postApplicationAction(
    application: TrackedApplication,
    action: "archive" | "restore" | "reject" | "withdraw",
    fallbackMessage: string
  ) {
    setPendingArchiveApplicationId(application.id);
    setMessage("");

    try {
      const response = await fetch(`${apiBasePath}/applications/${application.id}/${action}`, { method: "POST" });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      if (!payload || typeof payload !== "object" || !("application" in payload)) {
        throw new Error("Applications API returned an unexpected response.");
      }

      setApplications((current) => current.map((item) => (item.id === application.id ? (payload.application as TrackedApplication) : item)));
      setHighlightedApplicationId(application.id);
      setMessageKind("success");
      setMessage(actionResultMessage(payload, fallbackMessage));
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      if (application.job_id) {
        window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      }
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : `Could not ${action} application.`);
    } finally {
      setPendingArchiveApplicationId(null);
    }
  }

  return (
    <main className="dashboard-main application-workspace">
      <section className="page-heading">
        <p className="eyebrow">Application pipeline</p>
        <h1>Applications</h1>
        <p>Convert saved jobs into in-progress applications and track submitted roles without manual entry.</p>
      </section>

      {message ? <p className={`profile-workspace-message ${messageKind}`}>{message}</p> : null}

      <section className="application-list" aria-labelledby="application-list-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Pipeline</p>
            <h2 id="application-list-title">Applications</h2>
          </div>
          <span>{applicationCounts[activeBucket]}</span>
        </div>

        <div className="queue-tabs" role="tablist" aria-label="Application queue filters">
          {applicationTabs.map((tab) => (
            <button
              aria-selected={activeBucket === tab.id}
              className={`queue-tab${activeBucket === tab.id ? " active" : ""}`}
              key={tab.id}
              onClick={() => setActiveBucket(tab.id)}
              role="tab"
              suppressHydrationWarning
              type="button"
            >
              <span>{tab.label}</span>
              <strong>{applicationCounts[tab.id]}</strong>
            </button>
          ))}
        </div>

        {sortedApplications.length > 0 ? (
          <div className="application-card-grid">
            {sortedApplications.map((application) => (
              <article
                className={`application-card${highlightedApplicationId === application.id ? " application-card-highlighted" : ""}`}
                id={applicationCardId(application.id)}
                key={application.id}
              >
                <div className="application-card-main">
                  <div className="application-card-header">
                    <div>
                      <h2>{application.job_title}</h2>
                      <p>{application.company_name}</p>
                    </div>
                    <div className="application-card-badges">
                      <span className={`application-status application-status-${applicationDisplayClass(application)}`}>
                        {applicationDisplayBucket(application)}
                      </span>
                      {shouldShowUnderlyingStatus(application) ? (
                        <span className={`application-status application-status-${underlyingStatusClass(application.status)}`}>
                          {formatStatus(application.status)}
                        </span>
                      ) : null}
                      {application.latest_material_bundle ? <span className="application-status application-status-offer">Materials ready</span> : null}
                    </div>
                  </div>

                  <FoldedText className="application-notes" fallback="No notes yet" value={application.notes} />
                  <FoldedText className="application-fit" value={application.fit_summary} />
                  {application.job_url ? (
                    <div className="company-links application-card-primary-link" aria-label={`${application.job_title} primary link`}>
                      <a href={application.job_url} rel="noopener noreferrer" target="_blank">
                        Job post
                      </a>
                    </div>
                  ) : null}
                </div>

                <aside className="application-card-rail" aria-label={`${application.job_title} application details`}>
                  <div className="record-rail-section">
                    <dl className="application-details record-detail-grid">
                      <div>
                        <dt>Posted</dt>
                        <dd>{formatDateOnly(application.posting_date ?? null)}</dd>
                      </div>
                      <div>
                        <dt>Location</dt>
                        <dd>{application.location || formatOptionalStatus(application.remote_work_mode ?? null)}</dd>
                      </div>
                      <div>
                        <dt>Compensation</dt>
                        <dd>{application.salary_text || "Unknown"}</dd>
                      </div>
                      <div>
                        <dt>Employment</dt>
                        <dd>{application.employment_type || "Unknown"}</dd>
                      </div>
                    </dl>
                  </div>

                  <div className="record-rail-section">
                    <dl className="application-details record-detail-grid">
                      <div>
                        <dt>Source</dt>
                        <dd>{application.source || application.source_provider || "Unknown"}</dd>
                      </div>
                      <div>
                        <dt>Created</dt>
                        <dd>{formatDateTime(application.created_at)}</dd>
                      </div>
                      <div>
                        <dt>Applied</dt>
                        <dd>{formatDateOnly(application.date_applied)}</dd>
                      </div>
                      <div>
                        <dt>Status</dt>
                        <dd>{formatStatus(application.status)}</dd>
                      </div>
                    </dl>
                  </div>

                  <div className="company-links application-card-actions" aria-label={`${application.job_title} actions`}>
                    <Link className="secondary-action compact-action" href={applicationDetailHref(workspaceBasePath, application.id)}>
                      View Application
                    </Link>
                    {!application.archived_at && canMarkApplied(application) ? (
                      <button
                        className="secondary-action compact-action"
                        disabled={pendingApplicationId === application.id}
                        suppressHydrationWarning
                        type="button"
                        onClick={() => markApplied(application)}
                      >
                        {pendingApplicationId === application.id ? "Saving..." : "Mark applied"}
                      </button>
                    ) : null}
                    {!application.archived_at ? (
                      <>
                        <button
                          className="secondary-action compact-action"
                          disabled={pendingArchiveApplicationId === application.id}
                          suppressHydrationWarning
                          type="button"
                          onClick={() => postApplicationAction(application, "archive", "Application archived.")}
                        >
                          {pendingArchiveApplicationId === application.id ? "Saving..." : "Archive"}
                        </button>
                        {canMarkTerminal(application) ? (
                          <>
                            <button
                              className="secondary-action compact-action"
                              disabled={pendingArchiveApplicationId === application.id}
                              suppressHydrationWarning
                              type="button"
                              onClick={() => postApplicationAction(application, "reject", "Application marked rejected and archived.")}
                            >
                              Reject
                            </button>
                            <button
                              className="secondary-action compact-action"
                              disabled={pendingArchiveApplicationId === application.id}
                              suppressHydrationWarning
                              type="button"
                              onClick={() => postApplicationAction(application, "withdraw", "Application marked withdrawn and archived.")}
                        >
                          Withdraw
                        </button>
                      </>
                    ) : null}
                      </>
                    ) : (
                      <button
                        className="secondary-action compact-action"
                        disabled={pendingArchiveApplicationId === application.id}
                        suppressHydrationWarning
                        type="button"
                        onClick={() => postApplicationAction(application, "restore", "Application restored.")}
                      >
                        {pendingArchiveApplicationId === application.id ? "Saving..." : "Restore"}
                      </button>
                    )}
                  </div>
                </aside>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state-block">
            <h2>{activeEmptyState.title}</h2>
            <p>{activeEmptyState.body}</p>
          </div>
        )}
      </section>
    </main>
  );
}

export function ApplicationMaterials({
  bundle,
  defaultOpen = false,
  roomy = false
}: {
  bundle: ApplicationMaterialBundle;
  defaultOpen?: boolean;
  roomy?: boolean;
}) {
  const sortedItems = [...(bundle.items || [])].sort((left, right) => left.sort_order - right.sort_order);
  return (
    <details className={`application-materials${roomy ? " application-materials-roomy" : ""}`} open={defaultOpen}>
      <summary>
        <span>Application Materials</span>
        <time dateTime={bundle.created_at}>{formatDateTime(bundle.created_at)}</time>
      </summary>
      <div className="application-materials-body">
        {sortedItems.map((item) => (
          <section className="application-material-section" key={item.id}>
            <h3>{item.title}</h3>
            <MarkdownText value={item.content} />
          </section>
        ))}
      </div>
    </details>
  );
}

function MarkdownText({ value }: { value: string }) {
  return <pre className="application-material-content">{value}</pre>;
}

export function apiErrorMessage(payload: unknown, status: number) {
  if (payload && typeof payload === "object" && "error" in payload && typeof payload.error === "string") {
    return payload.error;
  }
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  if (payload && typeof payload === "object" && "detail" in payload) {
    const formattedDetail = formatApiDetail(payload.detail);
    if (formattedDetail) {
      return formattedDetail;
    }
  }
  return `Applications API request failed with HTTP ${status}.`;
}

function formatApiDetail(detail: unknown) {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail.map(formatValidationIssue).filter(Boolean);
    return messages.length > 0 ? messages.join(" ") : null;
  }
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    return detail.message;
  }
  return null;
}

function formatValidationIssue(issue: unknown) {
  if (!issue || typeof issue !== "object") {
    return null;
  }
  const message = "msg" in issue && typeof issue.msg === "string" ? issue.msg : null;
  if (!message) {
    return null;
  }
  if (!("loc" in issue) || !Array.isArray(issue.loc)) {
    return message;
  }
  const field = issue.loc.filter((part) => typeof part === "string").pop();
  return field ? `${formatStatus(field)}: ${message}.` : `${message}.`;
}

function applicationCardId(applicationId: string) {
  return `application-${applicationId}`;
}

export function formatStatus(status: string) {
  return status.replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

const applicationEmptyStates: Record<ApplicationBucketId, { title: string; body: string }> = {
  started: {
    title: "No started applications.",
    body: "Start an application from a saved job and it will appear here."
  },
  applied: {
    title: "No applied applications.",
    body: "Applications you've submitted, rejected, withdrawn, or restored from archive will appear here."
  },
  "in-process": {
    title: "No applications in process.",
    body: "When an application moves into callback, interview, or active process, it will appear here."
  },
  archived: {
    title: "No archived applications.",
    body: "Archived applications are hidden from your active workflow, but saved materials and history are preserved."
  }
};

export function applicationBucket(application: TrackedApplication): ApplicationBucketId {
  if (application.archived_at) {
    return "archived";
  }
  if (application.status === "saved" || application.status === "started") {
    return "started";
  }
  if (isInProcessApplicationStatus(application.status)) {
    return "in-process";
  }
  return "applied";
}

export function buildApplicationBucketCounts(applications: TrackedApplication[]): Record<ApplicationBucketId, number> {
  return applications.reduce(
    (counts, application) => {
      counts[applicationBucket(application)] += 1;
      return counts;
    },
    { started: 0, applied: 0, "in-process": 0, archived: 0 }
  );
}

export function sortApplicationsForBucket(applications: TrackedApplication[], bucket: ApplicationBucketId) {
  return [...applications].sort((left, right) => applicationSortDate(right, bucket).localeCompare(applicationSortDate(left, bucket)));
}

function defaultApplicationBucket(applications: TrackedApplication[]): ApplicationBucketId {
  const counts = buildApplicationBucketCounts(applications);
  return applicationTabs.find((tab) => counts[tab.id] > 0)?.id ?? "started";
}

export function applicationDisplayBucket(application: TrackedApplication) {
  const bucket = applicationBucket(application);
  return applicationTabs.find((tab) => tab.id === bucket)?.label ?? "Applied";
}

export function applicationDisplayClass(application: TrackedApplication) {
  return applicationBucket(application);
}

export function canMarkApplied(application: TrackedApplication) {
  return ["saved", "started", "in_progress", "in_process"].includes(application.status);
}

export function canMarkTerminal(application: TrackedApplication) {
  return application.status === "applied";
}

export function canReopenTerminal(application: TrackedApplication) {
  return application.status === "rejected" || application.status === "withdrawn";
}

export function shouldShowUnderlyingStatus(application: TrackedApplication) {
  return application.archived_at ? true : !["saved", "started", "in_progress", "in_process", "interviewing", "offer", "applied"].includes(application.status);
}

export function underlyingStatusClass(status: string) {
  if (isInProcessApplicationStatus(status)) {
    return "in-process";
  }
  if (status === "saved" || status === "started") {
    return "started";
  }
  return status;
}

function isInProcessApplicationStatus(status: string) {
  return ["in_process", "in_progress", "interviewing", "offer"].includes(status);
}

function applicationSortDate(application: TrackedApplication, bucket: ApplicationBucketId) {
  if (bucket === "started") {
    return application.created_at;
  }
  if (bucket === "applied") {
    return application.date_applied ?? application.created_at;
  }
  if (bucket === "in-process") {
    return application.updated_at;
  }
  return application.archived_at ?? "";
}

export function actionResultMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "message" in payload && typeof payload.message === "string") {
    return payload.message;
  }
  return fallback;
}

export function formatOptionalStatus(value: string | null) {
  if (!value || value === "unknown") {
    return "Unknown";
  }
  return formatStatus(value);
}

export function FoldedText({ value, className, fallback }: { value?: string | null; className: string; fallback?: string }) {
  if (!value) {
    return fallback ? <p className={className}>{fallback}</p> : null;
  }
  const preview = previewText(value);
  if (preview === value) {
    return <p className={className}>{value}</p>;
  }
  return (
    <details className={`folded-text ${className}`}>
      <summary>{preview}</summary>
      <p>{value}</p>
    </details>
  );
}

function previewText(value: string) {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= 145) {
    return compact;
  }
  return `${compact.slice(0, 145).trimEnd()}...`;
}

export function formatDateOnly(value: string | null) {
  if (!value) {
    return "Not set";
  }

  const [year, month, day] = value.split("-");
  if (!year || !month || !day) {
    return value;
  }

  return `${month}/${day}/${year}`;
}

export function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

export function applicationDetailHref(workspaceBasePath: string, applicationId: string) {
  return `${workspaceBasePath}/applications/${encodeURIComponent(applicationId)}`;
}
