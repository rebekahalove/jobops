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
  location: string | null;
  remote_work_mode: string | null;
  employment_type: string | null;
  salary_text: string | null;
  description_excerpt: string | null;
  fit_summary: string | null;
  user_notes: string | null;
  status: string;
  added_at: string;
  archived_at: string | null;
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

  useEffect(() => {
    let active = true;

    async function loadJobs() {
      try {
        const response = await fetch(`${apiBasePath}/jobs`, { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as SavedJob[];
        if (active) {
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
                <div className="job-card-header">
                  <div>
                    <h2>{job.title}</h2>
                    <p>{job.company_name}</p>
                  </div>
                  <div className="company-badges" aria-label={`${job.title} status`}>
                    <span>{formatStatus(job.status)}</span>
                    {job.source ? <span>{job.source}</span> : null}
                  </div>
                </div>

                {job.description_excerpt ? <p className="job-description">{job.description_excerpt}</p> : null}
                {job.fit_summary ? <p className="job-fit">{job.fit_summary}</p> : null}

                <dl className="job-details">
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
                    <dd>{job.salary_text || "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Added</dt>
                    <dd>{formatDateTime(job.added_at)}</dd>
                  </div>
                  <div>
                    <dt>Posted</dt>
                    <dd>{formatDateOnly(job.posting_date)}</dd>
                  </div>
                </dl>

                <div className="company-links" aria-label={`${job.title} links`}>
                  <a href={job.job_url} rel="noopener noreferrer" target="_blank">
                    Job posting
                  </a>
                  {job.apply_url && job.apply_url !== job.job_url ? (
                    <a href={job.apply_url} rel="noopener noreferrer" target="_blank">
                      Apply link
                    </a>
                  ) : null}
                </div>
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

function formatStatus(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

function formatOptionalStatus(value: string | null) {
  if (!value || value === "unknown") {
    return "Unknown";
  }
  return formatStatus(value);
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
