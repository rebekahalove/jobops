"use client";

import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";

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
  const [pendingApplicationId, setPendingApplicationId] = useState<string | null>(null);
  const [pendingArchiveApplicationId, setPendingArchiveApplicationId] = useState<string | null>(null);
  const [highlightedApplicationId, setHighlightedApplicationId] = useState<string | null>(null);

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
            setMessage(apiErrorMessage(payload, response.status));
          }
          return;
        }
        if (!Array.isArray(payload)) {
          if (active) {
            setMessage("Applications API returned an unexpected response.");
          }
          return;
        }
        if (active) {
          setMessage("");
          setApplications(payload);
        }
      } catch {
        if (active) {
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

  const sortedApplications = useMemo(
    () =>
      [...applications].sort((left, right) => {
        const leftDate = left.date_applied ?? left.created_at;
        const rightDate = right.date_applied ?? right.created_at;
        return rightDate.localeCompare(leftDate);
      }),
    [applications]
  );

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
      setMessage("Application marked applied.");
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
    } catch (error) {
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
      setMessage(actionResultMessage(payload, fallbackMessage));
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      if (application.job_id) {
        window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      }
    } catch (error) {
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

      {message ? <p className="application-message">{message}</p> : null}

      <section className="application-list" aria-labelledby="application-list-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Pipeline</p>
            <h2 id="application-list-title">Applications</h2>
          </div>
          <span>{applications.length}</span>
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
            <h2>No applications yet</h2>
            <p>Click Apply on a saved job to start an application.</p>
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

export function applicationDisplayBucket(application: TrackedApplication) {
  if (application.archived_at) {
    return "Archived";
  }
  if (application.status === "started" || application.status === "saved") {
    return "Started";
  }
  if (application.status === "in_process" || application.status === "in_progress") {
    return "In process";
  }
  return "Applied";
}

export function applicationDisplayClass(application: TrackedApplication) {
  if (application.archived_at) {
    return "archived";
  }
  if (application.status === "started" || application.status === "saved") {
    return "started";
  }
  if (application.status === "in_process" || application.status === "in_progress") {
    return "in-process";
  }
  return "applied";
}

export function canMarkApplied(application: TrackedApplication) {
  return ["saved", "started", "in_progress", "in_process"].includes(application.status);
}

export function canMarkTerminal(application: TrackedApplication) {
  return application.status === "applied";
}

export function shouldShowUnderlyingStatus(application: TrackedApplication) {
  return application.archived_at ? true : !["saved", "started", "in_progress", "in_process", "applied"].includes(application.status);
}

export function underlyingStatusClass(status: string) {
  if (status === "in_process" || status === "in_progress") {
    return "in-process";
  }
  if (status === "saved" || status === "started") {
    return "started";
  }
  return status;
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
