"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";
import { CompanyCard, formatDate, formatStatus, safeExternalUrl, type TrackedCompany } from "./companies-list";

export type CompanyDetailJob = {
  id: string;
  saved_job_id?: string | null;
  title: string;
  company_name: string;
  job_url?: string | null;
  canonical_url?: string | null;
  apply_url?: string | null;
  source_url?: string | null;
  source_provider?: string | null;
  provider_type?: string | null;
  ats_provider?: string | null;
  ats_board_token?: string | null;
  location?: string | null;
  remote_work_mode?: string | null;
  employment_type?: string | null;
  salary_text?: string | null;
  description_excerpt?: string | null;
  full_description?: string | null;
  description_html?: string | null;
  source_status?: string | null;
  is_active: boolean;
  posting_date?: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  saved_status?: string | null;
  saved_archived_at?: string | null;
  has_application?: boolean;
  application_id?: string | null;
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

  useEffect(() => {
    let active = true;

    async function loadCompany() {
      try {
        const response = await fetch(`${apiBasePath}/companies/${companyId}`, { cache: "no-store" });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          if (active) {
            setMessage(apiErrorMessage(payload, response.status));
          }
          return;
        }
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
          if (active) {
            setMessage("Company API returned an unexpected response.");
          }
          return;
        }
        if (active) {
          setCompany(payload as CompanyDetailRecord);
          setMessage("");
        }
      } catch {
        if (active) {
          setMessage("Company API is unavailable. Start FastAPI to load this company.");
        }
      }
    }

    loadCompany();
    return () => {
      active = false;
    };
  }, [apiBasePath, companyId]);

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
            {activeJobs.map((job) => (
              <CompanyJobCard job={job} key={job.id} workspaceBasePath={workspaceBasePath} />
            ))}
            {inactiveJobs.length > 0 ? (
              <details className="company-detail-collapsed">
                <summary>Closed or inactive jobs ({inactiveJobs.length})</summary>
                <div className="company-related-grid">
                  {inactiveJobs.map((job) => (
                    <CompanyJobCard job={job} key={job.id} workspaceBasePath={workspaceBasePath} />
                  ))}
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

function CompanyJobCard({ job, workspaceBasePath }: { job: CompanyDetailJob; workspaceBasePath: string }) {
  const postingUrl = safeExternalUrl(job.job_url) || safeExternalUrl(job.canonical_url) || safeExternalUrl(job.source_url);
  const applyUrl = safeExternalUrl(job.apply_url);
  return (
    <article className="company-related-card">
      <div>
        <div className="company-card-header">
          <div>
            <h3>{job.title}</h3>
            <p>{job.location || "Unknown location"}</p>
          </div>
          <div className="job-card-badges">
            <span className={`application-status ${job.is_active ? "application-status-highlight" : "application-status-archived"}`}>
              {job.is_active ? "Active" : "Inactive"}
            </span>
            {job.saved_job_id ? <span className="application-status application-status-highlight">On jobs list</span> : null}
            {job.has_application ? <span className="application-status application-status-applied">Application</span> : null}
          </div>
        </div>
        <dl className="company-details record-detail-grid company-related-details">
          <DetailItem label="Posted" value={formatDate(job.posting_date)} />
          <DetailItem label="Source" value={formatStatus(job.source_provider || "unknown")} />
          <DetailItem label="Work mode" value={formatStatus(job.remote_work_mode)} />
          <DetailItem label="Employment" value={job.employment_type || "Unknown"} />
          <DetailItem label="Compensation" value={job.salary_text || "Unknown"} />
          <DetailItem label="Status" value={formatStatus(job.saved_status || job.source_status || "unknown")} />
        </dl>
        <section className="job-info-panel company-related-description">
          <h3>Job Description</h3>
          <div className="job-scroll-text company-scroll-text">
            {job.description_html ? (
              <div dangerouslySetInnerHTML={{ __html: job.description_html }} />
            ) : (
              <p>{job.full_description || job.description_excerpt || "No description available."}</p>
            )}
          </div>
        </section>
      </div>
      <div className="company-links company-card-actions" aria-label={`${job.title} actions`}>
        {postingUrl ? (
          <a href={postingUrl} rel="noopener noreferrer" target="_blank">
            View Posting
          </a>
        ) : null}
        {applyUrl ? (
          <a href={applyUrl} rel="noopener noreferrer" target="_blank">
            Apply
          </a>
        ) : null}
        {job.application_id ? <Link href={`${workspaceBasePath}/applications/${job.application_id}`}>View Application</Link> : null}
      </div>
    </article>
  );
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
