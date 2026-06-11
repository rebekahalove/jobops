"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import type { JobSearchProviderDiagnostic, JobSearchRunStatus } from "../lib/command-center-contract";

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
  job_id: string | null;
  job_listing_id?: string | null;
  jobSearchRunId?: string | null;
  highlighted?: boolean;
  justAdded?: boolean;
  latestDiscoveryRunId?: string | null;
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
              <article className={`job-card${isJustAddedJob(job) ? " job-card-just-added" : ""}`} id={`saved-job-${job.id}`} key={job.id}>
                <div className="job-card-main">
                  <div className="job-card-header">
                    <div>
                      <h2>{job.title}</h2>
                      <p>{job.company_name}</p>
                    </div>
                    <div className="job-card-badges">
                      {isJustAddedJob(job) ? <span className="application-status application-status-highlight">Just added</span> : null}
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

export function JobDiscoveryDiagnostics({
  apiBasePath = "/api",
  initialRun = null
}: {
  apiBasePath?: string;
  initialRun?: JobSearchRunStatus | null;
}) {
  const [latestJobSearchRun, setLatestJobSearchRun] = useState<JobSearchRunStatus | null>(initialRun);
  const [isDiagnosticsLoading, setIsDiagnosticsLoading] = useState(false);
  const [diagnosticsStatusMessage, setDiagnosticsStatusMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timeoutId: number | null = null;

    async function loadLatestRunStatus() {
      if (timeoutId) {
        window.clearTimeout(timeoutId);
        timeoutId = null;
      }
      setIsDiagnosticsLoading(true);
      try {
        const response = await fetch(`${apiBasePath}/job-search-runs/latest`, { cache: "no-store" });
        const payload = (await response.json().catch(() => null)) as unknown;
        if (!active) {
          return;
        }
        if (response.status === 404) {
          setLatestJobSearchRun(null);
          setDiagnosticsStatusMessage("No recent job discovery run diagnostics found.");
          return;
        }
        if (!response.ok || !isJobSearchRunStatus(payload)) {
          setDiagnosticsStatusMessage(`Job discovery diagnostics could not be loaded (HTTP ${response.status}).`);
          return;
        }
        setLatestJobSearchRun(payload);
        setDiagnosticsStatusMessage(null);
        if (isActiveJobSearchRunStatus(payload.status)) {
          timeoutId = window.setTimeout(loadLatestRunStatus, 2500);
        }
      } catch {
        if (active) {
          setDiagnosticsStatusMessage("Job discovery diagnostics API is unavailable.");
        }
      } finally {
        if (active) {
          setIsDiagnosticsLoading(false);
        }
      }
    }

    loadLatestRunStatus();
    window.addEventListener("jobops:jobs-updated", loadLatestRunStatus);
    return () => {
      active = false;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
      window.removeEventListener("jobops:jobs-updated", loadLatestRunStatus);
    };
  }, [apiBasePath]);

  return <JobDiscoveryDiagnosticsPanel isLoading={isDiagnosticsLoading} run={latestJobSearchRun} statusMessage={diagnosticsStatusMessage} />;
}

function JobDiscoveryDiagnosticsPanel({
  run,
  isLoading,
  statusMessage
}: {
  run: JobSearchRunStatus | null;
  isLoading: boolean;
  statusMessage: string | null;
}) {
  const diagnostics = run?.diagnostics;
  const modelReview = diagnostics?.modelReview;
  const providerRows = diagnostics?.providerDiagnostics ?? [];
  const criteria = diagnostics?.searchCriteria;
  const replanning = diagnostics?.replanning;
  const explanation = diagnostics?.modelExplanation;
  const isActive = run ? isActiveJobSearchRunStatus(run.status) : false;
  const hasDbBackedDiagnostics = Boolean(diagnostics?.jobSync || diagnostics?.databaseQueries);
  const providerTimeline = buildProviderSearchTimeline(providerRows, replanning, criteria);

  const summaryText = run ? jobDiscoveryRunDigest(run) : statusMessage || (isLoading ? "Waiting for run status..." : "No recent job discovery diagnostics yet.");

  return (
    <section className="job-discovery-diagnostics" aria-labelledby="job-discovery-diagnostics-title">
      <details open={isActive}>
        <summary>
          <span>
            <strong id="job-discovery-diagnostics-title">Discovery diagnostics</strong>
            <small>{summaryText}</small>
          </span>
          <span className="diagnostics-toggle-label">Details</span>
        </summary>

        {run ? (
          <div className="job-discovery-diagnostics-body">
            <section className="diagnostics-section">
              <h3>Summary</h3>
              <dl className="diagnostics-grid">
                <DiagnosticItem label="Status" value={formatStatus(run.status)} />
                <DiagnosticItem label="Saved jobs" value={`${formatNumber(run.savedCount) ?? "0"} newly saved`} />
                <DiagnosticItem label="Provider matches" value={`${formatNumber(run.providerResultCount) ?? "0"} normalized jobs returned by providers`} />
                <DiagnosticItem label="Unique candidates" value={`${formatNumber(run.candidateCountAfterDedupe) ?? "0"} after URL/title dedupe`} />
                <DiagnosticItem label="Sent to model" value={`${formatNumber(run.candidatePoolCount) ?? "0"} candidates in final review pool`} />
                <DiagnosticItem label="Selected by model" value={`${formatNumber(run.modelSelectedCount) ?? "0"} jobs recommended to save`} />
              </dl>
              {isActive ? <p className="diagnostics-muted">Running... diagnostics will fill in as provider results arrive.</p> : null}
            </section>

            {hasDbBackedDiagnostics ? (
              <DbBackedDiagnosticsSections run={run} />
            ) : (
              <>
            <section className="diagnostics-section">
              <h3>Initial search plan</h3>
              <dl className="diagnostics-grid">
                <DiagnosticItem label="Mode" value={criteria?.searchMode ? formatStatus(criteria.searchMode) : "Unknown"} />
                <DiagnosticItem label="Role queries" value={formatList(criteria?.roleQueries)} />
                <DiagnosticItem label="Companies" value={formatList(criteria?.companyNames)} />
                <DiagnosticItem label="Locations" value={formatList(criteria?.locations)} />
                <DiagnosticItem label="Work modes" value={formatList(criteria?.remoteWorkModes)} />
                <DiagnosticItem label="Salary minimum" value={formatNumber(criteria?.salaryMin) ?? "None"} />
                <DiagnosticItem label="Exclusions" value={formatList(criteria?.excludeTerms)} />
                <DiagnosticItem label="Max provider pages" value={formatNumber(criteria?.maxProviderPages) ?? "Unknown"} />
              </dl>
            </section>

            <section className="diagnostics-section">
              <h3>Provider search timeline</h3>
              {providerTimeline.length ? (
                <div className="diagnostics-provider-list">
                  {providerTimeline.map((entry, index) => (
                    entry.type === "initial" ? (
                      <InitialSearchTimelineRow criteria={entry.criteria} key={`initial-search-${index}`} />
                    ) : entry.type === "replan" ? (
                      <ReplanTimelineRow event={entry} key={`replan-${entry.attempt}-${entry.query}-${index}`} />
                    ) : (
                      <ProviderDiagnosticRow
                        key={`${entry.provider.providerName}-${entry.provider.companyName}-${entry.provider.queryPreview}-${index}`}
                        provider={entry.provider}
                      />
                    )
                  ))}
                </div>
              ) : (
                <p className="diagnostics-muted">Waiting for provider results...</p>
              )}
            </section>

            <section className="diagnostics-section">
              <h3>Model review</h3>
              <dl className="diagnostics-grid">
                <DiagnosticItem label="Unique candidates" value={`${formatNumber(modelReview?.candidateCountAfterDedupe) ?? "0"} after provider result dedupe`} />
                <DiagnosticItem label="Sent to model" value={`${formatNumber(modelReview?.candidatePoolCount) ?? "0"} final candidates`} />
                <DiagnosticItem label="Selected by model" value={`${formatNumber(modelReview?.modelSelectedCount) ?? "0"} save recommendations`} />
                <DiagnosticItem label="Saved" value={`${formatNumber(modelReview?.savedCount) ?? "0"} new saved jobs`} />
                <DiagnosticItem label="Refreshed" value={`${formatNumber(modelReview?.updatedExistingCount) ?? "0"} existing saved jobs refreshed`} />
                <DiagnosticItem label="Duplicates" value={`${formatNumber(modelReview?.duplicateCount) ?? "0"} already-saved or duplicate save attempts`} />
                <DiagnosticItem label="Skipped" value={`${formatNumber(modelReview?.skippedCount) ?? "0"} provider/model candidates not saved`} />
                <DiagnosticItem label="Provider errors" value={formatNumber(modelReview?.providerErrorCount) ?? "0"} />
              </dl>
            </section>

            <section className="diagnostics-section">
              <h3>Model explanation</h3>
              <p>{explanation?.userVisibleSummary || explanation?.selectionAssistantMessage || run.userVisibleSummary || run.message}</p>
              {explanation?.plannerRationale ? <p className="diagnostics-muted">Planner: {explanation.plannerRationale}</p> : null}
              {explanation?.skippedCandidateNotes?.length ? (
                <ul className="diagnostics-note-list">
                  {explanation.skippedCandidateNotes.slice(0, 5).map((note) => (
                    <li key={`${note.candidateId}-${note.reason}`}>
                      <strong>{note.candidateId}</strong>: {note.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
              </>
            )}
          </div>
        ) : (
          <div className="job-discovery-diagnostics-body">
            <section className="diagnostics-section">
              <h3>Summary</h3>
              <p className="diagnostics-muted">{statusMessage || "Loading latest job discovery run..."}</p>
            </section>
          </div>
        )}
      </details>
    </section>
  );
}

function DbBackedDiagnosticsSections({ run }: { run: JobSearchRunStatus }) {
  const diagnostics = run.diagnostics;
  const syncRows = diagnostics?.jobSync?.runs ?? [];
  const queryRows = diagnostics?.databaseQueries?.queries ?? [];
  const modelReview = diagnostics?.modelReview;
  const reasonCounts = modelReview?.topRejectionReasonCounts ?? modelReview?.rejectionReasonCounts ?? {};

  return (
    <>
      <section className="diagnostics-section">
        <h3>Job Sync</h3>
        {syncRows.length ? (
          <div className="diagnostics-provider-list">
            {syncRows.map((row, index) => (
              <article className="diagnostics-provider-row" key={`${row.syncKey}-${row.status}-${index}`}>
                <div className="diagnostics-event-header">
                  <strong>{row.syncKey || "job_sync"}</strong>
                  <span>{formatStatus(row.status || "unknown")}</span>
                </div>
                <div className="diagnostics-event-meta">
                  <CompactDetailItem item={{ label: "Raw", value: formatNumber(row.raw) ?? "0" }} />
                  <CompactDetailItem item={{ label: "Normalized", value: formatNumber(row.normalized) ?? "0" }} />
                  <CompactDetailItem item={{ label: "Created", value: formatNumber(row.created) ?? "0" }} />
                  <CompactDetailItem item={{ label: "Updated", value: formatNumber(row.updated) ?? "0" }} />
                  {row.failed ? <CompactDetailItem item={{ label: "Failed", value: formatNumber(row.failed) ?? "0" }} /> : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="diagnostics-muted">No sync runs were recorded for this discovery run.</p>
        )}
      </section>

      <section className="diagnostics-section">
        <h3>Database queries</h3>
        {queryRows.length ? (
          <div className="diagnostics-provider-list">
            {queryRows.map((row, index) => (
              <article className="diagnostics-provider-row" key={`${row.label}-${index}`}>
                <div className="diagnostics-event-header">
                  <strong>{row.label || "Synced job inventory search"}</strong>
                  <span>{formatNumber(row.jobCount) ?? "0"} jobs</span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="diagnostics-muted">No database query rows were recorded.</p>
        )}
        <p className="diagnostics-muted">Unique jobs in pool: {formatNumber(diagnostics?.databaseQueries?.uniqueJobPoolCount) ?? "0"}</p>
      </section>

      <section className="diagnostics-section">
        <h3>Model review</h3>
        <dl className="diagnostics-grid">
          <DiagnosticItem label="Unique jobs in pool" value={formatNumber(modelReview?.uniqueJobsInPool) ?? "0"} />
          <DiagnosticItem label="Jobs reviewed by model" value={formatNumber(modelReview?.jobsReviewedByModel) ?? "0"} />
          <DiagnosticItem label="Added to candidate jobs list" value={formatNumber(modelReview?.addedToCandidateJobsList) ?? "0"} />
          <DiagnosticItem label="Recorded model rejections" value={formatNumber(modelReview?.recordedModelRejections) ?? "0"} />
          <DiagnosticItem label="Model review completed" value={modelReview?.modelReviewCompleted === false ? "No" : "Yes"} />
        </dl>
        {modelReview?.modelReviewFailureReason ? <p className="diagnostics-muted">Failure reason: {modelReview.modelReviewFailureReason}</p> : null}
        {run.noJobsAddedReason || diagnostics?.noJobsAddedReason ? (
          <p className="diagnostics-muted">No jobs added: {formatNoJobsAddedReason(run.noJobsAddedReason || diagnostics?.noJobsAddedReason)}</p>
        ) : null}
        {Object.keys(reasonCounts).length ? (
          <p className="diagnostics-muted">Top rejection reasons: {formatReasonCounts(reasonCounts)}</p>
        ) : null}
      </section>
    </>
  );
}

function DiagnosticItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || "None"}</dd>
    </div>
  );
}

type JobSearchReplanningDiagnostics = NonNullable<NonNullable<JobSearchRunStatus["diagnostics"]>["replanning"]>;
type JobSearchCriteriaDiagnostics = NonNullable<NonNullable<JobSearchRunStatus["diagnostics"]>["searchCriteria"]>;
type ProviderTimelineEntry =
  | { type: "initial"; criteria: JobSearchCriteriaDiagnostics }
  | { type: "provider"; provider: JobSearchProviderDiagnostic }
  | {
      type: "replan";
      attempt: number;
      label: string;
      message: string;
      query: string | null;
      triggerSource: string;
    };

function ProviderDiagnosticRow({ provider }: { provider: JobSearchProviderDiagnostic }) {
  const details = providerSearchDetails(provider);
  const stats = providerSearchStats(provider);

  return (
    <article className="diagnostics-provider-row">
      <div className="diagnostics-event-header">
        <strong>{providerSearchTitle(provider)}</strong>
        <span>
          {[providerHeaderSearchIdentity(provider), stats].filter(Boolean).join(" - ")}
        </span>
      </div>
      <div className="diagnostics-event-meta">
        {details.length ? details.map((item) => <CompactDetailItem item={item} key={`${item.label}-${item.value}`} />) : <span>No search criteria recorded.</span>}
      </div>
    </article>
  );
}

function InitialSearchTimelineRow({ criteria }: { criteria: JobSearchCriteriaDiagnostics }) {
  return (
    <article className="diagnostics-initial-row">
      <div className="diagnostics-event-header">
        <strong>Initial search</strong>
        <span>{criteria.searchMode ? formatStatus(criteria.searchMode) : "Search plan"}</span>
      </div>
      <div className="diagnostics-event-meta">
        {initialSearchDetails(criteria).map((item) => <CompactDetailItem item={item} key={`${item.label}-${item.value}`} />)}
      </div>
    </article>
  );
}

function ReplanTimelineRow({ event }: { event: Extract<ProviderTimelineEntry, { type: "replan" }> }) {
  return (
    <article className="diagnostics-replan-row">
      <div className="diagnostics-event-header">
        <strong>Replan {event.attempt}</strong>
        <span>{event.triggerSource}</span>
      </div>
      <div className="diagnostics-event-meta">
        <CompactDetailItem item={{ label: "message", value: event.message }} />
        <CompactDetailItem item={{ label: "reason", value: event.label }} />
        {event.query ? <CompactDetailItem item={{ label: "Next query", value: event.query }} /> : null}
      </div>
    </article>
  );
}

function CompactDetailItem({ item }: { item: { label: string; value: string } }) {
  return (
    <span>
      <strong>{item.label}:</strong> {item.value}
    </span>
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
  return [...jobs].sort((left, right) => {
    const highlightRank = Number(isJustAddedJob(left)) - Number(isJustAddedJob(right));
    if (highlightRank !== 0) {
      return -highlightRank;
    }
    return jobSortDate(right, bucket).localeCompare(jobSortDate(left, bucket));
  });
}

function isJustAddedJob(job: SavedJob) {
  return Boolean(job.justAdded || job.highlighted);
}

function defaultJobBucket(jobs: SavedJob[]): JobBucketId {
  const counts = buildJobBucketCounts(jobs);
  return jobTabs.find((tab) => counts[tab.id] > 0)?.id ?? "new";
}

function isJobSearchRunStatus(value: unknown): value is JobSearchRunStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const payload = value as Record<string, unknown>;
  return (
    typeof payload.id === "string" &&
    typeof payload.status === "string" &&
    typeof payload.providerResultCount === "number" &&
    typeof payload.candidateCountAfterDedupe === "number" &&
    typeof payload.modelSelectedCount === "number" &&
    typeof payload.savedCount === "number" &&
    typeof payload.duplicateCount === "number" &&
    typeof payload.skippedCount === "number" &&
    typeof payload.message === "string"
  );
}

function isActiveJobSearchRunStatus(status: string) {
  return ["queued", "started", "running"].includes(status);
}

function jobDiscoveryRunDigest(run: JobSearchRunStatus) {
  return [
    formatStatus(run.status),
    `${run.savedCount} saved`,
    `${run.modelSelectedCount} model selected`,
    `${run.candidatePoolCount} sent to model`,
    `${run.candidateCountAfterDedupe} unique candidates`,
    `${run.providerResultCount} provider matches`
  ].join(" - ");
}

function buildProviderSearchTimeline(
  providers: JobSearchProviderDiagnostic[],
  replanning?: JobSearchReplanningDiagnostics,
  criteria?: JobSearchCriteriaDiagnostics
): ProviderTimelineEntry[] {
  const initialEntries: ProviderTimelineEntry[] = criteria ? [{ type: "initial", criteria }] : [];
  if (!replanning?.replansAttempted || replanning.replansAttempted < 1) {
    return [...initialEntries, ...providers.map((provider) => ({ type: "provider" as const, provider }))];
  }

  const queries = replanning.replanQueries ?? [];
  const reasons = replanning.replanReasons ?? [];
  const entries: ProviderTimelineEntry[] = [...initialEntries];
  const insertedAttempts = new Set<number>();

  providers.forEach((provider) => {
    const matchedAttempt = firstUninsertedReplanAttemptForProvider(provider, queries, insertedAttempts);
    if (matchedAttempt !== null) {
      entries.push(buildReplanTimelineEntry(replanning, matchedAttempt, queries[matchedAttempt - 1] ?? null, reasons[matchedAttempt - 1] ?? null));
      insertedAttempts.add(matchedAttempt);
    }
    entries.push({ type: "provider", provider });
  });

  const attempts = replanning.replansAttempted ?? queries.length;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    if (!insertedAttempts.has(attempt)) {
      entries.push(buildReplanTimelineEntry(replanning, attempt, queries[attempt - 1] ?? null, reasons[attempt - 1] ?? null));
    }
  }

  return entries;
}

function firstUninsertedReplanAttemptForProvider(provider: JobSearchProviderDiagnostic, queries: string[], insertedAttempts: Set<number>) {
  const providerQuery = normalizeSearchText(provider.queryPreview);
  if (!providerQuery) {
    return null;
  }
  for (let index = 0; index < queries.length; index += 1) {
    const attempt = index + 1;
    const replanQuery = normalizeSearchText(queries[index]);
    if (!insertedAttempts.has(attempt) && replanQuery && providerQuery.includes(replanQuery)) {
      return attempt;
    }
  }
  return null;
}

function buildReplanTimelineEntry(
  replanning: JobSearchReplanningDiagnostics,
  attempt: number,
  query: string | null,
  reason: string | null
): Extract<ProviderTimelineEntry, { type: "replan" }> {
  const label = replanning.displayLabel || (reason ? formatStatus(reason) : "Replan triggered");
  return {
    type: "replan",
    attempt,
    label,
    message: replanning.displayMessage || "JobOps adjusted the search plan before continuing provider searches.",
    query,
    triggerSource: formatTriggerSource(replanning.triggerProviderName, replanning.triggerProviderType)
  };
}

function providerSearchStats(provider: JobSearchProviderDiagnostic) {
  return [
    `${formatNumber(provider.rawResultCount ?? provider.resultCount) ?? "0"} raw`,
    `${formatNumber(provider.normalizedResultCount ?? provider.resultCount) ?? "0"} matched`,
    provider.totalMatches !== null && provider.totalMatches !== undefined ? `${formatNumber(provider.totalMatches) ?? "0"} total` : null,
    provider.page ? `page ${formatNumber(provider.page)}` : null
  ]
    .filter(Boolean)
    .join(" / ");
}

function providerSearchTitle(provider: JobSearchProviderDiagnostic) {
  if (provider.providerType === "ats_board") {
    return [
      provider.providerName || "ATS board",
      "ATS board",
      provider.companyName
    ].filter(Boolean).join(" - ");
  }
  return [
    provider.providerName || "Provider search",
    provider.providerType ? formatStatus(provider.providerType) : null
  ].filter(Boolean).join(" - ");
}

function providerHeaderSearchIdentity(provider: JobSearchProviderDiagnostic) {
  if (provider.providerType === "ats_board" || provider.providerType === "broad_search") {
    return null;
  }
  return [
    provider.queryPreview ? `Query: ${provider.queryPreview}` : null,
    provider.searchMode ? `Mode: ${formatStatus(provider.searchMode)}` : null,
    provider.companyName ? `Company: ${provider.companyName}` : null,
    provider.boardToken ? `Board: ${provider.boardToken}` : null
  ].filter(Boolean).join(" - ");
}

function providerSearchDetails(provider: JobSearchProviderDiagnostic) {
  const criteria = provider.requestCriteria ?? {};
  const items: Array<{ label: string; value: string }> = [];
  addCriteriaItem(items, "Query", provider.queryPreview || criteriaString(criteria.what));
  if (provider.providerType !== "ats_board" && provider.providerType !== "broad_search") {
    addCriteriaItem(items, "Provider", provider.providerName ?? null);
    addCriteriaItem(items, "Type", provider.providerType ? formatStatus(provider.providerType) : null);
  }
  if (provider.providerType !== "ats_board") {
    addCriteriaItem(items, "Where", criteriaString(criteria.where));
    addCriteriaItem(items, "Exclude", criteriaString(criteria.whatExclude));
    addCriteriaItem(items, "Company", provider.companyName ?? null);
    addCriteriaItem(items, "Country", criteriaString(criteria.country));
  }
  if (provider.providerType !== "ats_board" && provider.providerType !== "broad_search") {
    addCriteriaItem(items, "Mode", provider.searchMode ? formatStatus(provider.searchMode) : null);
    addCriteriaItem(items, "Raw", formatNumber(provider.rawResultCount));
    addCriteriaItem(items, "Matched", formatNumber(provider.normalizedResultCount ?? provider.resultCount));
  }
  addCriteriaItem(items, "Board token", provider.boardToken ?? null);
  addCriteriaItem(items, "Attempted", provider.attempted === undefined ? null : provider.attempted ? "yes" : "no");
  addCriteriaItem(items, "Configured", provider.configured === undefined ? null : provider.configured ? "yes" : "no");
  addCriteriaItem(items, "Total", formatNumber(provider.totalMatches));
  addCriteriaItem(items, "Deduped", formatNumber(provider.dedupedResultCount));
  addCriteriaItem(items, "After filters", formatNumber(provider.candidateCountAfterFilters));
  addCriteriaItem(items, "Page", formatNumber(provider.page ?? criteriaNumber(criteria.page)));
  addCriteriaItem(items, "Pages attempted", formatNumber(provider.pagesAttempted));
  addCriteriaItem(items, "Results/page", formatNumber(criteriaNumber(criteria.resultsPerPage)));
  addCriteriaItem(items, "Reason", provider.reason ?? null);
  addCriteriaItem(items, "Error", provider.errorSummary ?? null);
  return items;
}

function initialSearchDetails(criteria: JobSearchCriteriaDiagnostics) {
  const items: Array<{ label: string; value: string }> = [];
  addCriteriaItem(items, "Mode", criteria.searchMode ? formatStatus(criteria.searchMode) : null);
  addCriteriaItem(items, "Role queries", formatList(criteria.roleQueries));
  addCriteriaItem(items, "Companies", formatList(criteria.companyNames));
  addCriteriaItem(items, "Locations", formatList(criteria.locations));
  addCriteriaItem(items, "Work modes", formatList(criteria.remoteWorkModes));
  addCriteriaItem(items, "Salary minimum", formatNumber(criteria.salaryMin));
  addCriteriaItem(items, "Exclusions", formatList(criteria.excludeTerms));
  addCriteriaItem(items, "Max provider pages", formatNumber(criteria.maxProviderPages));
  return items.length ? items : [{ label: "Plan", value: "No initial search criteria recorded." }];
}

function addCriteriaItem(items: Array<{ label: string; value: string }>, label: string, value?: string | null) {
  if (value && value !== "None") {
    items.push({ label, value });
  }
}

function criteriaString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function criteriaNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function normalizeSearchText(value: unknown) {
  return typeof value === "string" ? value.trim().toLowerCase().replace(/\s+/g, " ") : "";
}

function formatList(values?: string[] | null) {
  if (!values || values.length === 0) {
    return "None";
  }
  return values.join(", ");
}

function formatNumber(value?: number | null) {
  return typeof value === "number" ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value) : null;
}

function formatNoJobsAddedReason(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  const labels: Record<string, string> = {
    no_db_matches: "No synced jobs matched the database search",
    model_review_failed: "Model review did not complete",
    model_selected_zero: "Model review selected zero jobs",
    review_validation_removed_all_selected_ids: "Model returned job IDs outside the reviewed pool",
    all_selected_jobs_already_on_list: "Selected jobs were already on the jobs list",
    unknown: "Unknown"
  };
  return labels[value] ?? formatStatus(value);
}

function formatReasonCounts(value: Record<string, number>) {
  return Object.entries(value)
    .slice(0, 5)
    .map(([reason, count]) => `${formatStatus(reason)}: ${count}`)
    .join(", ");
}

function formatTriggerSource(providerName?: string | null, providerType?: string | null) {
  const name = providerName && providerName !== "unknown" ? providerName : "Unknown source";
  const type = providerType && providerType !== "unknown" ? formatStatus(providerType) : null;
  return type ? `${name} (${type})` : name;
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
