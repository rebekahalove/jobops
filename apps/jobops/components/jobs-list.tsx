"use client";

import React, { useEffect, useMemo, useState } from "react";

export type SavedJob = {
  id: string;
  candidate_profile_id: string;
  job_id: string;
  title: string;
  company_name: string;
  job_url: string;
  canonical_url: string | null;
  apply_url: string | null;
  source: string | null;
  source_provider?: string | null;
  source_result_id?: string | null;
  source_query?: string | null;
  source_url?: string | null;
  provenance?: string | null;
  url_verification_status?: string | null;
  url_verification_checked_at?: string | null;
  url_verification_summary?: string | null;
  location: string | null;
  remote_work_mode: string | null;
  employment_type: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  salary_text: string | null;
  description_excerpt: string | null;
  fit_summary: string | null;
  user_notes: string | null;
  status: string;
  added_at: string;
  archived_at: string | null;
  archived_reason?: string | null;
  archived_by_action?: string | null;
  has_application?: boolean;
  application_id?: string | null;
  application_status?: string | null;
  application_archived_at?: string | null;
  posting_date: string | null;
  first_seen_at: string;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
};

export function JobsList({
  apiBasePath = "/api",
  initialJobs = []
}: {
  apiBasePath?: string;
  initialJobs?: SavedJob[];
}) {
  const [jobs, setJobs] = useState(initialJobs);
  const [message, setMessage] = useState("");
  const [pendingApplyJobId, setPendingApplyJobId] = useState<string | null>(null);
  const [pendingArchiveJobId, setPendingArchiveJobId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadJobs() {
      try {
        const response = await fetch(`${apiBasePath}/jobs`, { cache: "no-store" });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          if (active) {
            setMessage(apiErrorMessage(payload, response.status));
          }
          return;
        }
        if (!Array.isArray(payload)) {
          if (active) {
            setMessage("Saved jobs API returned an unexpected response.");
          }
          return;
        }
        if (active) {
          setMessage("");
          setJobs(payload);
        }
      } catch {
        if (active) {
          setMessage("Saved jobs API is unavailable. Start FastAPI to load saved records.");
        }
      }
    }

    loadJobs();
    window.addEventListener("jobops:jobs-updated", loadJobs);
    return () => {
      active = false;
      window.removeEventListener("jobops:jobs-updated", loadJobs);
    };
  }, [apiBasePath]);

  const sortedJobs = useMemo(
    () => [...jobs].sort((left, right) => right.added_at.localeCompare(left.added_at)),
    [jobs]
  );

  async function applyToJob(job: SavedJob) {
    if (job.application_id) {
      setMessage(applicationAlreadyExistsMessage(job));
      navigateToApplication(job.application_id);
      return;
    }

    setPendingApplyJobId(job.id);
    setMessage("");

    try {
      const response = await fetch(`${apiBasePath}/applications`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          saved_job_id: job.id,
          status: "in_process"
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }

      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      navigateToApplication(payload.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start application.");
    } finally {
      setPendingApplyJobId(null);
    }
  }

  async function setJobArchiveState(job: SavedJob, action: "archive" | "restore") {
    setPendingArchiveJobId(job.id);
    setMessage("");

    try {
      const response = await fetch(`${apiBasePath}/jobs/${job.id}/${action}`, { method: "POST" });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      if (!payload || typeof payload !== "object" || !("job" in payload)) {
        throw new Error("Saved jobs API returned an unexpected response.");
      }

      setJobs((current) => current.map((item) => (item.id === job.id ? (payload.job as SavedJob) : item)));
      setMessage(actionResultMessage(payload, action === "archive" ? "Job archived." : "Job restored."));
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      if ("application_id" in payload && payload.application_id) {
        window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `Could not ${action} job.`);
    } finally {
      setPendingArchiveJobId(null);
    }
  }

  return (
    <main className="dashboard-main job-workspace">
      <section className="page-heading">
        <p className="eyebrow">Saved job search</p>
        <h1>Jobs</h1>
        <p>Review discovered roles saved from reliable source links. Applications and materials attach later.</p>
      </section>

      {message ? <p className="application-message">{message}</p> : null}

      <section className="job-list" aria-labelledby="job-list-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Job leads</p>
            <h2 id="job-list-title">Saved jobs</h2>
          </div>
          <span>{jobs.length}</span>
        </div>

        {sortedJobs.length > 0 ? (
          <div className="job-card-grid">
            {sortedJobs.map((job) => (
              <article className="job-card" key={job.id}>
                <div className="job-card-main">
                  <div className="job-card-header">
                    <div>
                      <h2>{job.title}</h2>
                      <p>{job.company_name}</p>
                    </div>
                    <div className="job-card-badges">
                      {job.archived_at ? <span className="application-status application-status-archived">Archived</span> : null}
                      {job.has_application ? (
                        <span className={`application-status application-status-${applicationBadgeClass(job)}`}>
                          {applicationBadgeLabel(job)}
                        </span>
                      ) : null}
                    </div>
                  </div>

                  <FoldedText className="job-description" value={job.description_excerpt} />
                  <FoldedText className="job-fit" value={job.fit_summary} />
                  {shouldShowVerificationSummary(job) ? <FoldedText className="job-verification" value={job.url_verification_summary} /> : null}
                </div>

                <aside className="job-card-rail" aria-label={`${job.title} details`}>
                  <div className="record-rail-section">
                    <dl className="job-details record-detail-grid">
                      <div>
                        <dt>Location</dt>
                        <dd>{job.location || "Unknown"}</dd>
                      </div>
                      <div>
                        <dt>Work mode</dt>
                        <dd>{formatOptionalStatus(job.remote_work_mode)}</dd>
                      </div>
                      <div>
                        <dt>Employment</dt>
                        <dd>{job.employment_type || "Unknown"}</dd>
                      </div>
                      <div>
                        <dt>Compensation</dt>
                        <dd>{formatCompensation(job)}</dd>
                      </div>
                      <div>
                        <dt>Posted</dt>
                        <dd>{formatDateOnly(job.posting_date)}</dd>
                      </div>
                    </dl>
                  </div>

                  <div className="record-rail-section">
                    <dl className="job-details record-detail-grid">
                      <div>
                        <dt>Saved</dt>
                        <dd>{formatDateTime(job.added_at)}</dd>
                      </div>
                      <div>
                        <dt>Status</dt>
                        <dd>{formatStatus(job.status)}</dd>
                      </div>
                      <div>
                        <dt>Source</dt>
                        <dd>{job.source || job.source_provider || "Unknown"}</dd>
                      </div>
                      <div>
                        <dt>Provenance</dt>
                        <dd>{job.provenance ? formatStatus(job.provenance) : "Unknown"}</dd>
                      </div>
                      {isVerifiedJobUrl(job) ? (
                        <div>
                          <dt>URL check</dt>
                          <dd>Verified</dd>
                        </div>
                      ) : null}
                    </dl>
                  </div>

                  <div className="company-links" aria-label={`${job.title} links`}>
                    <button
                      className="secondary-action compact-action"
                      disabled={pendingApplyJobId === job.id || Boolean(job.archived_at)}
                      suppressHydrationWarning
                      type="button"
                      onClick={() => applyToJob(job)}
                    >
                      {pendingApplyJobId === job.id ? "Starting..." : job.application_id ? "Open application" : "Apply"}
                    </button>
                    <button
                      className="secondary-action compact-action"
                      disabled={pendingArchiveJobId === job.id}
                      suppressHydrationWarning
                      type="button"
                      onClick={() => setJobArchiveState(job, job.archived_at ? "restore" : "archive")}
                    >
                      {pendingArchiveJobId === job.id ? "Saving..." : job.archived_at ? "Restore" : "Archive"}
                    </button>
                    <a href={job.job_url} rel="noopener noreferrer" target="_blank">
                      Job posting
                    </a>
                    {job.apply_url && job.apply_url !== job.job_url ? (
                      <a href={job.apply_url} rel="noopener noreferrer" target="_blank">
                        Apply link
                      </a>
                    ) : null}
                  </div>
                </aside>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state-block">
            <h2>No saved jobs yet</h2>
            <p>Ask the AI Command Center to find jobs that fit your profile. Saved postings will appear here with source links.</p>
          </div>
        )}
      </section>
    </main>
  );
}

function apiErrorMessage(payload: unknown, status: number) {
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
  return `Saved jobs API request failed with HTTP ${status}.`;
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

function formatStatus(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

function formatOptionalStatus(value: string | null) {
  if (!value || value === "unknown") {
    return "Unknown";
  }
  return formatStatus(value);
}

function shouldShowVerificationSummary(job: SavedJob) {
  return Boolean(job.url_verification_summary && isVerifiedJobUrl(job));
}

function isVerifiedJobUrl(job: SavedJob) {
  return job.url_verification_status === "verified" || job.url_verification_status === "mock_verified";
}

function applicationBadgeLabel(job: SavedJob) {
  if (job.application_archived_at) {
    return "Application archived";
  }
  if (job.application_status) {
    return applicationDisplayLabel(job.application_status);
  }
  return "Application started";
}

function applicationBadgeClass(job: SavedJob) {
  if (job.application_archived_at) {
    return "archived";
  }
  if (job.application_status === "in_process" || job.application_status === "in_progress") {
    return "in-process";
  }
  if (job.application_status === "started" || job.application_status === "saved") {
    return "started";
  }
  return "applied";
}

function applicationAlreadyExistsMessage(job: SavedJob) {
  const label = job.application_archived_at ? "An archived application" : "An application";
  return `${label} already exists for this job. Saved materials and history are preserved.`;
}

function applicationDisplayLabel(status: string) {
  if (status === "started" || status === "saved") {
    return "Application started";
  }
  if (status === "in_process" || status === "in_progress") {
    return "In process";
  }
  if (status === "applied") {
    return "Applied";
  }
  return formatStatus(status);
}

function actionResultMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "message" in payload && typeof payload.message === "string") {
    return payload.message;
  }
  return fallback;
}

function navigateToApplication(applicationId: string) {
  if (typeof window === "undefined") {
    return;
  }
  const currentUrl = new URL(window.location.href);
  const nextPath = currentUrl.pathname.endsWith("/jobs") ? currentUrl.pathname.replace(/\/jobs$/, "/applications") : "/applications";
  window.location.assign(`${nextPath}?applicationId=${encodeURIComponent(applicationId)}`);
}

function FoldedText({ value, className }: { value?: string | null; className: string }) {
  if (!value) {
    return null;
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

function formatCompensation(job: SavedJob) {
  const formatted = formatSalaryRange(job.salary_min ?? null, job.salary_max ?? null, job.salary_currency ?? null);
  return formatted || job.salary_text || "Unknown";
}

function formatSalaryRange(salaryMin: number | null, salaryMax: number | null, currencyCode: string | null) {
  if (salaryMin === null && salaryMax === null) {
    return null;
  }
  const formatter = buildCurrencyFormatter(currencyCode);
  if (salaryMin !== null && salaryMax !== null) {
    if (salaryMin === salaryMax) {
      return formatter(salaryMin);
    }
    return `${formatter(salaryMin)}-${formatter(salaryMax)}`;
  }
  return formatter(salaryMin ?? salaryMax ?? 0);
}

function buildCurrencyFormatter(currencyCode: string | null) {
  const normalizedCurrency = currencyCode && /^[A-Z]{3}$/.test(currencyCode) ? currencyCode : null;
  const formatter = new Intl.NumberFormat(undefined, {
    ...(normalizedCurrency ? { style: "currency", currency: normalizedCurrency, currencyDisplay: "narrowSymbol" } : {}),
    maximumFractionDigits: 0,
    minimumFractionDigits: 0
  });
  return (value: number) => formatter.format(Math.round(value));
}

function formatDateOnly(value: string | null) {
  if (!value) {
    return "Unknown";
  }
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) {
    return value;
  }
  return `${month}/${day}/${year}`;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}
