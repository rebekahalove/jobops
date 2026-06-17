"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";
import { CompanyCard, formatDate, formatStatus, safeExternalUrl, type TrackedCompany } from "./companies-list";
import { JobCard, isFavoriteJobStatus, type SavedJob } from "./jobs-list";

export type CompanyDetailJob = {
  id: string;
  saved_job_id?: string | null;
  candidate_profile_id?: string | null;
  job_listing_id?: string | null;
  jobSearchRunId?: string | null;
  highlighted?: boolean;
  justAdded?: boolean;
  latestDiscoveryRunId?: string | null;
  title: string;
  company_name: string;
  job_url?: string | null;
  canonical_url?: string | null;
  apply_url?: string | null;
  source?: string | null;
  source_url?: string | null;
  source_provider?: string | null;
  source_result_id?: string | null;
  source_query?: string | null;
  provider_type?: string | null;
  ats_provider?: string | null;
  ats_board_token?: string | null;
  provenance?: string | null;
  url_verification_status?: string | null;
  url_verification_checked_at?: string | null;
  url_verification_summary?: string | null;
  location?: string | null;
  remote_work_mode?: string | null;
  employment_type?: string | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  salary_text?: string | null;
  description_excerpt?: string | null;
  full_description?: string | null;
  description_html?: string | null;
  fit_summary?: string | null;
  user_notes?: string | null;
  source_status?: string | null;
  is_active: boolean;
  posting_date?: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  saved_status?: string | null;
  added_at?: string | null;
  saved_archived_at?: string | null;
  archived_reason?: string | null;
  archived_by_action?: string | null;
  has_application?: boolean;
  application_id?: string | null;
  application_status?: string | null;
  application_archived_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type CompanyDetailApplication = {
  id: string;
  saved_job_id?: string | null;
  company_id?: string | null;
  company_name: string;
  job_title: string;
  job_url?: string | null;
  location?: string | null;
  source?: string | null;
  status: string;
  date_applied?: string | null;
  next_follow_up_date?: string | null;
  archived_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type CompanyDetailRecord = TrackedCompany & {
  jobs: CompanyDetailJob[];
  applications: CompanyDetailApplication[];
};

export function CompanyDetail({
  apiBasePath = "/api",
  companyId,
  initialCompany = null,
  workspaceBasePath = ""
}: {
  apiBasePath?: string;
  companyId: string;
  initialCompany?: CompanyDetailRecord | null;
  workspaceBasePath?: string;
}) {
  const [company, setCompany] = useState<CompanyDetailRecord | null>(initialCompany);
  const [message, setMessage] = useState("");
  const [pendingAddJobListingId, setPendingAddJobListingId] = useState<string | null>(null);
  const [pendingApplyJobId, setPendingApplyJobId] = useState<string | null>(null);
  const [pendingArchiveJobId, setPendingArchiveJobId] = useState<string | null>(null);
  const [pendingFavoriteJobId, setPendingFavoriteJobId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadCompany() {
      try {
        const payload = await fetchCompanyDetail(apiBasePath, companyId);
        if (active) {
          setCompany(payload);
          setMessage("");
        }
      } catch (error) {
        if (active) {
          setMessage(error instanceof Error ? error.message : "Company API is unavailable. Start FastAPI to load this company.");
        }
      }
    }

    loadCompany();
    return () => {
      active = false;
    };
  }, [apiBasePath, companyId]);

  async function reloadCompany() {
    const payload = await fetchCompanyDetail(apiBasePath, companyId);
    setCompany(payload);
    setMessage("");
  }

  async function applyToJob(job: SavedJob) {
    if (job.application_id) {
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
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      if (!payload || typeof payload !== "object" || !("id" in payload) || typeof payload.id !== "string") {
        throw new Error("Applications API returned an unexpected response.");
      }
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      navigateToApplication(workspaceBasePath, payload.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not start application.");
    } finally {
      setPendingApplyJobId(null);
    }
  }

  async function addToJobsList(job: SavedJob) {
    if (!job.job_listing_id) {
      setMessage("This job cannot be added because it is missing its canonical job listing.");
      return;
    }

    setPendingAddJobListingId(job.job_listing_id);
    setMessage("");
    try {
      const response = await fetch(`${apiBasePath}/jobs/from-listing/${encodeURIComponent(job.job_listing_id)}`, { method: "POST" });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      await reloadCompany();
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not add job to your jobs list.");
    } finally {
      setPendingAddJobListingId(null);
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
      await reloadCompany();
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
      if (payload && typeof payload === "object" && "application_id" in payload && payload.application_id) {
        window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      }
    } catch (error) {
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
      await reloadCompany();
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `Could not ${action} job.`);
    } finally {
      setPendingFavoriteJobId(null);
    }
  }

  function renderCompanyJobCard(job: CompanyDetailJob) {
    const savedJob = companyJobToSavedJob(job);
    const isSavedListJob = Boolean(job.saved_job_id);
    return (
      <JobCard
        job={savedJob}
        key={job.id}
        onAddToJobsList={!isSavedListJob ? addToJobsList : undefined}
        onApply={isSavedListJob ? applyToJob : undefined}
        onArchiveToggle={isSavedListJob ? (selectedJob) => setJobArchiveState(selectedJob, selectedJob.archived_at ? "restore" : "archive") : undefined}
        onFavoriteToggle={
          isSavedListJob ? (selectedJob) => setJobFavoriteState(selectedJob, isFavoriteJobStatus(selectedJob.status) ? "unfavorite" : "favorite") : undefined
        }
        pendingAddJobListingId={pendingAddJobListingId}
        pendingApplyJobId={pendingApplyJobId}
        pendingArchiveJobId={pendingArchiveJobId}
        pendingFavoriteJobId={pendingFavoriteJobId}
        workspaceBasePath={workspaceBasePath}
      />
    );
  }

  if (!company) {
    return (
      <main className="dashboard-main company-detail-workspace">
        <section className="page-heading">
          <p className="eyebrow">Company detail</p>
          <h1>Company</h1>
          <p>{message || "Loading company..."}</p>
          <Link className="application-card-primary-link" href={`${workspaceBasePath}/companies`}>
            Back to companies
          </Link>
        </section>
      </main>
    );
  }

  const activeJobs = company.jobs.filter((job) => job.is_active);
  const inactiveJobs = company.jobs.filter((job) => !job.is_active);

  return (
    <main className="dashboard-main company-detail-workspace">
      <section className="page-heading">
        <p className="eyebrow">Company detail</p>
        <h1>{company.name}</h1>
        <p>Review provider metadata, synced jobs, and applications connected to this company.</p>
        <Link className="application-card-primary-link" href={`${workspaceBasePath}/companies`}>
          Back to companies
        </Link>
      </section>

      {message ? <p className="application-message">{message}</p> : null}

      <section className="company-detail-section" aria-label={`${company.name} summary`}>
        <CompanyCard company={company} workspaceBasePath={workspaceBasePath} />
      </section>

      <section className="company-detail-section" aria-labelledby="company-jobs-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Synced inventory</p>
            <h2 id="company-jobs-title">Company jobs</h2>
          </div>
          <span>{company.jobs.length}</span>
        </div>
        {company.jobs.length > 0 ? (
          <div className="company-related-grid">
            {activeJobs.map((job) => renderCompanyJobCard(job))}
            {inactiveJobs.length > 0 ? (
              <details className="company-detail-collapsed">
                <summary>Closed or inactive jobs ({inactiveJobs.length})</summary>
                <div className="company-related-grid">
                  {inactiveJobs.map((job) => renderCompanyJobCard(job))}
                </div>
              </details>
            ) : null}
          </div>
        ) : (
          <div className="empty-state-block">
            <h2>No synced jobs yet</h2>
            <p>This company does not have synced JobListing records yet.</p>
          </div>
        )}
      </section>

      <section className="company-detail-section" aria-labelledby="company-applications-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Applications</p>
            <h2 id="company-applications-title">Company applications</h2>
          </div>
          <span>{company.applications.length}</span>
        </div>
        {company.applications.length > 0 ? (
          <div className="company-related-grid">
            {company.applications.map((application) => (
              <CompanyApplicationCard application={application} key={application.id} workspaceBasePath={workspaceBasePath} />
            ))}
          </div>
        ) : (
          <div className="empty-state-block">
            <h2>No applications yet</h2>
            <p>No applications are associated with this company yet.</p>
          </div>
        )}
      </section>
    </main>
  );
}

function companyJobToSavedJob(job: CompanyDetailJob): SavedJob {
  return {
    id: job.saved_job_id || `job-listing-${job.id}`,
    candidate_profile_id: job.candidate_profile_id || "",
    job_listing_id: job.job_listing_id || job.id,
    jobSearchRunId: job.jobSearchRunId || null,
    highlighted: job.highlighted || false,
    justAdded: job.justAdded || false,
    latestDiscoveryRunId: job.latestDiscoveryRunId || null,
    title: job.title,
    company_name: job.company_name,
    job_url: job.job_url || "",
    canonical_url: job.canonical_url || null,
    apply_url: job.apply_url || null,
    source: job.source || job.source_provider || null,
    source_provider: job.source_provider || job.source || null,
    source_result_id: job.source_result_id || null,
    source_query: job.source_query || null,
    source_url: job.source_url || null,
    provenance: job.provenance || "job_sync",
    url_verification_status: job.url_verification_status || "provider_unverified",
    url_verification_checked_at: job.url_verification_checked_at || null,
    url_verification_summary: job.url_verification_summary || null,
    location: job.location || null,
    remote_work_mode: job.remote_work_mode || null,
    employment_type: job.employment_type || null,
    salary_min: job.salary_min || null,
    salary_max: job.salary_max || null,
    salary_currency: job.salary_currency || null,
    salary_text: job.salary_text || null,
    full_description: job.full_description || null,
    description_html: job.description_html || null,
    description_excerpt: job.description_excerpt || null,
    fit_summary: job.fit_summary || null,
    user_notes: job.user_notes || null,
    status: job.saved_status || job.source_status || (job.is_active ? "active" : "inactive"),
    added_at: job.added_at || job.first_seen_at || job.created_at || "",
    archived_at: job.saved_archived_at || null,
    archived_reason: job.archived_reason || null,
    archived_by_action: job.archived_by_action || null,
    has_application: job.has_application || false,
    application_id: job.application_id || null,
    application_status: job.application_status || null,
    application_archived_at: job.application_archived_at || null,
    posting_date: job.posting_date || null,
    first_seen_at: job.first_seen_at || "",
    last_seen_at: job.last_seen_at || null,
    created_at: job.created_at || job.first_seen_at || "",
    updated_at: job.updated_at || job.last_seen_at || job.first_seen_at || ""
  };
}

function CompanyApplicationCard({ application, workspaceBasePath }: { application: CompanyDetailApplication; workspaceBasePath: string }) {
  const jobUrl = safeExternalUrl(application.job_url);
  return (
    <article className="company-related-card">
      <div>
        <div className="company-card-header">
          <div>
            <h3>{application.job_title}</h3>
            <p>{application.location || "Unknown location"}</p>
          </div>
          <div className="job-card-badges">
            <span className={`application-status application-status-${application.archived_at ? "archived" : application.status}`}>
              {formatStatus(application.status)}
            </span>
          </div>
        </div>
        <dl className="company-details record-detail-grid company-related-details">
          <DetailItem label="Applied" value={formatDate(application.date_applied)} />
          <DetailItem label="Next follow-up" value={formatDate(application.next_follow_up_date)} />
          <DetailItem label="Source" value={formatStatus(application.source)} />
          <DetailItem label="Created" value={formatDate(application.created_at)} />
        </dl>
      </div>
      <div className="company-links company-card-actions" aria-label={`${application.job_title} application actions`}>
        <Link href={`${workspaceBasePath}/applications/${application.id}`}>View Application</Link>
        {jobUrl ? (
          <a href={jobUrl} rel="noopener noreferrer" target="_blank">
            View Posting
          </a>
        ) : null}
      </div>
    </article>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function apiErrorMessage(payload: unknown, status: number) {
  if (payload && typeof payload === "object" && "error" in payload && typeof payload.error === "string") {
    return payload.error;
  }
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return `Company API request failed with HTTP ${status}.`;
}

async function fetchCompanyDetail(apiBasePath: string, companyId: string) {
  const response = await fetch(`${apiBasePath}/companies/${companyId}`, { cache: "no-store" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(apiErrorMessage(payload, response.status));
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Company API returned an unexpected response.");
  }
  return payload as CompanyDetailRecord;
}

function navigateToApplication(workspaceBasePath: string, applicationId: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.location.assign(`${workspaceBasePath}/applications/${encodeURIComponent(applicationId)}`);
}
