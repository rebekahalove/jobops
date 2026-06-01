"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

export type JobBucketId = "new" | "favorites" | "applied" | "archived";

const jobTabs: Array<{ id: JobBucketId; label: string }> = [
  { id: "new", label: "New" },
  { id: "favorites", label: "Favorites" },
  { id: "applied", label: "Applied" },
  { id: "archived", label: "Archived" }
];

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
  workspaceBasePath = "",
  initialJobs = []
}: {
  apiBasePath?: string;
  workspaceBasePath?: string;
  initialJobs?: SavedJob[];
}) {
  const [jobs, setJobs] = useState(initialJobs);
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<"success" | "error" | "info">("info");
  const [pendingApplyJobId, setPendingApplyJobId] = useState<string | null>(null);
  const [pendingArchiveJobId, setPendingArchiveJobId] = useState<string | null>(null);
  const [pendingFavoriteJobId, setPendingFavoriteJobId] = useState<string | null>(null);
  const [activeBucket, setActiveBucket] = useState<JobBucketId>(() => defaultJobBucket(initialJobs));
  const hasAppliedInitialBucket = useRef(initialJobs.length > 0);

  useEffect(() => {
    if (!message) {
      return;
    }
    const timeout = window.setTimeout(() => setMessage(""), messageKind === "error" ? 9000 : 5200);
    return () => window.clearTimeout(timeout);
  }, [message, messageKind]);

  useEffect(() => {
    let active = true;

    async function loadJobs() {
      try {
        const response = await fetch(`${apiBasePath}/jobs`, { cache: "no-store" });
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
            setMessage("Saved jobs API returned an unexpected response.");
          }
          return;
        }
        if (active) {
          setMessage("");
          setJobs(payload);
          if (!hasAppliedInitialBucket.current) {
            setActiveBucket(defaultJobBucket(payload));
            hasAppliedInitialBucket.current = true;
          }
        }
      } catch {
        if (active) {
          setMessageKind("error");
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

  const jobCounts = useMemo(() => buildJobBucketCounts(jobs), [jobs]);
  const sortedJobs = useMemo(() => sortJobsForBucket(jobs.filter((job) => jobBucket(job) === activeBucket), activeBucket), [activeBucket, jobs]);
  const activeEmptyState = jobEmptyStates[activeBucket];

  async function applyToJob(job: SavedJob) {
    if (job.application_id) {
      setMessageKind("info");
      setMessage(applicationAlreadyExistsMessage(job));
      navigateToApplication(workspaceBasePath, job.application_id);
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
          status: "started"
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }

      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      navigateToApplication(workspaceBasePath, payload.id);
    } catch (error) {
      setMessageKind("error");
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
      setMessageKind("success");
      setMessage(actionResultMessage(payload, action === "archive" ? "Job archived." : "Job restored."));
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      if ("application_id" in payload && payload.application_id) {
        window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      }
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : `Could not ${action} job.`);
    } finally {
      setPendingArchiveJobId(null);
    }
  }

  async function setJobFavoriteState(job: SavedJob, action: "favorite" | "unfavorite") {
    setPendingFavoriteJobId(job.id);
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
      setMessageKind("success");
      setMessage(actionResultMessage(payload, action === "favorite" ? "Job added to Favorites." : "Job moved back to New."));
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : `Could not ${action} job.`);
    } finally {
      setPendingFavoriteJobId(null);
    }
  }

  return (
    <main className="dashboard-main job-workspace">
      <section className="page-heading">
        <p className="eyebrow">Saved job search</p>
        <h1>Jobs</h1>
        <p>Review discovered roles saved from reliable source links. Applications and materials attach later.</p>
      </section>

      {message ? <p className={`profile-workspace-message ${messageKind}`}>{message}</p> : null}

      <section className="job-list" aria-labelledby="job-list-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Job leads</p>
            <h2 id="job-list-title">Saved jobs</h2>
          </div>
          <span>{jobCounts[activeBucket]}</span>
        </div>

        <div className="queue-tabs" role="tablist" aria-label="Job queue filters">
          {jobTabs.map((tab) => (
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
              <strong>{jobCounts[tab.id]}</strong>
            </button>
          ))}
        </div>

        {sortedJobs.length > 0 ? (
          <div className="job-card-grid">
            {sortedJobs.map((job) => (
              <article className="job-card" id={`saved-job-${job.id}`} key={job.id}>
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
                      disabled={pendingApplyJobId === job.id || (Boolean(job.archived_at) && !job.application_id)}
                      suppressHydrationWarning
                      type="button"
                      onClick={() => applyToJob(job)}
                    >
                      {pendingApplyJobId === job.id ? "Starting..." : job.application_id ? "View application" : "Apply"}
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
                    {!job.archived_at && !job.application_id ? (
                      <button
                        className="secondary-action compact-action"
                        disabled={pendingFavoriteJobId === job.id}
                        suppressHydrationWarning
                        type="button"
                        onClick={() => setJobFavoriteState(job, isFavoriteJobStatus(job.status) ? "unfavorite" : "favorite")}
                      >
                        {pendingFavoriteJobId === job.id ? "Saving..." : isFavoriteJobStatus(job.status) ? "Unfavorite" : "Favorite"}
                      </button>
                    ) : null}
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
            <h2>{activeEmptyState.title}</h2>
            <p>{activeEmptyState.body}</p>
          </div>
        )}
      </section>
    </main>
  );
}

const jobEmptyStates: Record<JobBucketId, { title: string; body: string }> = {
  new: {
    title: "No new jobs.",
    body: "New jobs found by JobOps will appear here before you decide whether to apply."
  },
  favorites: {
    title: "No favorite jobs yet.",
    body: "Save jobs you want to apply to and they'll appear here."
  },
  applied: {
    title: "No jobs with applications yet.",
    body: "When you start an application from a job, it will appear here."
  },
  archived: {
    title: "No archived jobs.",
    body: "Archived jobs are hidden from your active queue, but saved application history and materials are preserved."
  }
};

export function jobBucket(job: SavedJob): JobBucketId {
  if (job.archived_at) {
    return "archived";
  }
  if (job.has_application || job.application_id) {
    return "applied";
  }
  if (isFavoriteJobStatus(job.status)) {
    return "favorites";
  }
  return "new";
}

export function buildJobBucketCounts(jobs: SavedJob[]): Record<JobBucketId, number> {
  return jobs.reduce(
    (counts, job) => {
      counts[jobBucket(job)] += 1;
      return counts;
    },
    { new: 0, favorites: 0, applied: 0, archived: 0 }
  );
}

export function sortJobsForBucket(jobs: SavedJob[], bucket: JobBucketId) {
  return [...jobs].sort((left, right) => jobSortDate(right, bucket).localeCompare(jobSortDate(left, bucket)));
}

function defaultJobBucket(jobs: SavedJob[]): JobBucketId {
  const counts = buildJobBucketCounts(jobs);
  return jobTabs.find((tab) => counts[tab.id] > 0)?.id ?? "new";
}

function isFavoriteJobStatus(status: string) {
  return ["favorite", "favorited", "saved", "watchlisted", "watchlist"].includes(status.toLowerCase());
}

function jobSortDate(job: SavedJob, bucket: JobBucketId) {
  if (bucket === "archived") {
    return job.archived_at ?? "";
  }
  if (bucket === "favorites") {
    return job.updated_at || job.added_at;
  }
  if (bucket === "applied") {
    return job.updated_at || job.added_at;
  }
  return job.added_at;
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
    return job.application_status ? applicationDisplayLabel(job.application_status) : "Application archived";
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

function navigateToApplication(workspaceBasePath: string, applicationId: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.location.assign(`${workspaceBasePath}/applications/${encodeURIComponent(applicationId)}`);
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
