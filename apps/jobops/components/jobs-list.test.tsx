import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import JobsPage from "../app/jobs/page";
import { JobsList, buildJobBucketCounts, jobBucket, sortJobsForBucket, type SavedJob } from "./jobs-list";
import MountedJobsPage from "../../portfolio/app/jobops/jobs/page";

describe("Jobs list", () => {
  it("renders the jobs workspace empty state", () => {
    const html = renderToStaticMarkup(<JobsPage />);

    expect(html).toContain("Saved job search");
    expect(html).toContain("Saved jobs");
    expect(html).toContain("No new jobs.");
    expect(html).toContain("New jobs found by JobOps will appear here before you decide whether to apply.");
  });

  it("renders the real jobs workspace in the mounted portfolio app", () => {
    const html = renderToStaticMarkup(<MountedJobsPage />);

    expect(html).toContain("Saved job search");
    expect(html).toContain("Saved jobs");
    expect(html).not.toContain("Coming soon");
  });

  it("renders saved jobs through the profile link with safe external links and dates", () => {
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          {
            id: "saved-job-1",
            candidate_profile_id: "profile-1",
            job_id: "job-1",
            title: "Applied AI Engineer",
            company_name: "Example Civic",
            job_url: "https://jobs.example.test/example-civic/applied-ai",
            canonical_url: "https://jobs.example.test/example-civic/applied-ai",
            apply_url: "https://jobs.example.test/example-civic/apply",
            source: "Company careers",
            provenance: "provider_result",
            url_verification_status: "verified",
            url_verification_checked_at: "2026-05-28T12:00:00Z",
            url_verification_summary: "Fetched page confirmed the job title and company.",
            location: "Remote US",
            remote_work_mode: "remote",
            employment_type: "Full-time",
            salary_min: 150000,
            salary_max: 180000,
            salary_currency: "USD",
            salary_text: "USD 150,000-180,000",
            description_excerpt: "Build applied AI workflows for civic data products.",
            fit_summary: "Matches applied AI and platform engineering goals.",
            user_notes: null,
            status: "saved",
            added_at: "2026-05-28T12:00:00Z",
            archived_at: null,
            has_application: true,
            application_id: "app-1",
            application_status: "in_process",
            application_archived_at: null,
            posting_date: "2026-05-20",
            first_seen_at: "2026-05-28T12:00:00Z",
            last_seen_at: "2026-05-28T12:00:00Z",
            created_at: "2026-05-28T12:00:00Z",
            updated_at: "2026-05-28T12:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain("Applied AI Engineer");
    expect(html).toContain("Example Civic");
    expect(html).toContain("Remote US");
    expect(html).toContain("Full-time");
    expect(html).toContain("$150,000-$180,000");
    expect(html).toContain("May 28, 2026");
    expect(html).toContain("05/20/2026");
    expect(html).toContain("URL check");
    expect(html).toContain("Verified");
    expect(html).toContain("Fetched page confirmed the job title and company.");
    expect(html).toContain("Matches applied AI and platform engineering goals.");
    expect(html).toContain("In process");
    expect(html).toContain("View application");
    expect(html).toContain("Archive");
    expect(html).toContain('href="https://jobs.example.test/example-civic/applied-ai"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("marks missing posting dates as unknown", () => {
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          {
            id: "saved-job-1",
            candidate_profile_id: "profile-1",
            job_id: "job-1",
            title: "AI Platform Engineer",
            company_name: "Example Civic",
            job_url: "https://jobs.example.test/example-civic/platform",
            canonical_url: null,
            apply_url: null,
            source: null,
            location: null,
            remote_work_mode: "unknown",
            employment_type: null,
            salary_text: null,
            description_excerpt: null,
            fit_summary: null,
            user_notes: null,
            status: "saved",
            added_at: "2026-05-28T12:00:00Z",
            archived_at: null,
            posting_date: null,
            first_seen_at: "2026-05-28T12:00:00Z",
            last_seen_at: null,
            created_at: "2026-05-28T12:00:00Z",
            updated_at: "2026-05-28T12:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain("AI Platform Engineer");
    expect(html).toContain("Unknown");
  });

  it("does not show noisy provider-unverified fetch summaries", () => {
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          {
            id: "saved-job-1",
            candidate_profile_id: "profile-1",
            job_id: "job-1",
            title: "Studio Assistant",
            company_name: "Example Studio",
            job_url: "https://provider.example/jobs/studio",
            canonical_url: null,
            apply_url: null,
            source: "Adzuna",
            provenance: "provider_result",
            url_verification_status: "provider_unverified",
            url_verification_checked_at: "2026-05-28T12:00:00Z",
            url_verification_summary: "Provider-backed URL could not be fully fetched/verified: Job URL returned HTTP 429.",
            location: null,
            remote_work_mode: "unknown",
            employment_type: null,
            salary_text: null,
            description_excerpt: null,
            fit_summary: null,
            user_notes: null,
            status: "saved",
            added_at: "2026-05-28T12:00:00Z",
            archived_at: null,
            posting_date: null,
            first_seen_at: "2026-05-28T12:00:00Z",
            last_seen_at: null,
            created_at: "2026-05-28T12:00:00Z",
            updated_at: "2026-05-28T12:00:00Z"
          }
        ]}
      />
    );

    expect(html).not.toContain("Provider unverified");
    expect(html).not.toContain("HTTP 429");
  });

  it("refreshes when command-center job discovery completes", async () => {
    const source = await readFile(new URL("./jobs-list.tsx", import.meta.url), "utf-8");
    const commandCenterSource = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain('window.addEventListener("jobops:jobs-updated", loadJobs)');
    expect(source).toContain('window.removeEventListener("jobops:jobs-updated", loadJobs)');
    expect(commandCenterSource).toContain('action.type === "job_discovery"');
    expect(commandCenterSource).toContain('window.dispatchEvent(new CustomEvent("jobops:jobs-updated"');
  });

  it("posts saved_job_id and navigates to the created application when applying", async () => {
    const source = await readFile(new URL("./jobs-list.tsx", import.meta.url), "utf-8");

    expect(source).toContain('body: JSON.stringify({');
    expect(source).toContain("saved_job_id: job.id");
    expect(source).toContain('status: "in_process"');
    expect(source).toContain('window.dispatchEvent(new CustomEvent("jobops:applications-updated"))');
    expect(source).toContain("navigateToApplication(workspaceBasePath, payload.id)");
    expect(source).toContain("job.application_id");
    expect(source).toContain("/applications/");
  });

  it("supports mounted application detail navigation for the portfolio app", async () => {
    const source = await readFile(new URL("../../portfolio/app/jobops/jobs/page.tsx", import.meta.url), "utf-8");

    expect(source).toContain('workspaceBasePath="/jobops"');
  });

  it("renders archived jobs with restore action and archived application badge", () => {
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          {
            id: "saved-job-1",
            candidate_profile_id: "profile-1",
            job_id: "job-1",
            title: "AI Platform Engineer",
            company_name: "Example Civic",
            job_url: "https://jobs.example.test/example-civic/platform",
            canonical_url: null,
            apply_url: null,
            source: null,
            location: null,
            remote_work_mode: "unknown",
            employment_type: null,
            salary_text: null,
            description_excerpt: null,
            fit_summary: null,
            user_notes: null,
            status: "saved",
            added_at: "2026-05-28T12:00:00Z",
            archived_at: "2026-05-29T12:00:00Z",
            has_application: true,
            application_id: "app-1",
            application_status: "rejected",
            application_archived_at: "2026-05-29T12:00:00Z",
            posting_date: null,
            first_seen_at: "2026-05-28T12:00:00Z",
            last_seen_at: null,
            created_at: "2026-05-28T12:00:00Z",
            updated_at: "2026-05-28T12:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain("Archived");
    expect(html).toContain("Application archived: Rejected");
    expect(html).toContain("View application");
    expect(html).toContain("Restore");
  });

  it("renders tabs with counts for each job queue", () => {
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          jobFixture({ id: "job-new", status: "new", title: "New Role" }),
          jobFixture({ id: "job-favorite", status: "saved", title: "Favorite Role" }),
          jobFixture({ id: "job-applied", has_application: true, application_id: "app-1", title: "Applied Role" }),
          jobFixture({ id: "job-archived", archived_at: "2026-05-18T00:00:00Z", title: "Archived Role" })
        ]}
      />
    );

    expect(html).toContain("New");
    expect(html).toContain("Favorites");
    expect(html).toContain("Applied");
    expect(html).toContain("Archived");
    expect(html).toContain("<strong>1</strong>");
  });

  it("buckets jobs with archived as an overlay", () => {
    const jobs = [
      jobFixture({ id: "new", status: "new" }),
      jobFixture({ id: "favorite", status: "favorite" }),
      jobFixture({ id: "favorited", status: "favorited" }),
      jobFixture({ id: "saved", status: "saved" }),
      jobFixture({ id: "watchlisted", status: "watchlisted" }),
      jobFixture({ id: "applied", status: "saved", has_application: true, application_id: "app-1" }),
      jobFixture({ id: "archived", status: "saved", archived_at: "2026-05-18T00:00:00Z", has_application: true, application_id: "app-2" })
    ];

    expect(jobs.map(jobBucket)).toEqual(["new", "favorites", "favorites", "favorites", "favorites", "applied", "archived"]);
    expect(buildJobBucketCounts(jobs)).toEqual({ new: 1, favorites: 4, applied: 1, archived: 1 });
  });

  it("sorts job queues by their requested dates", () => {
    const jobs = [
      jobFixture({ id: "older", added_at: "2026-05-10T00:00:00Z", updated_at: "2026-05-11T00:00:00Z" }),
      jobFixture({ id: "newer", added_at: "2026-05-12T00:00:00Z", updated_at: "2026-05-09T00:00:00Z" })
    ];

    expect(sortJobsForBucket(jobs, "new").map((job) => job.id)).toEqual(["newer", "older"]);
    expect(sortJobsForBucket(jobs, "favorites").map((job) => job.id)).toEqual(["older", "newer"]);
  });
});

function jobFixture(overrides: Partial<SavedJob> = {}): SavedJob {
  return {
    id: "saved-job-1",
    candidate_profile_id: "profile-1",
    job_id: "job-1",
    title: "Applied AI Engineer",
    company_name: "Example Civic",
    job_url: "https://jobs.example.test/example-civic/applied-ai",
    canonical_url: null,
    apply_url: null,
    source: null,
    location: null,
    remote_work_mode: "unknown",
    employment_type: null,
    salary_text: null,
    description_excerpt: null,
    fit_summary: null,
    user_notes: null,
    status: "new",
    added_at: "2026-05-13T00:00:00Z",
    archived_at: null,
    has_application: false,
    application_id: null,
    application_status: null,
    application_archived_at: null,
    posting_date: null,
    first_seen_at: "2026-05-13T00:00:00Z",
    last_seen_at: null,
    created_at: "2026-05-13T00:00:00Z",
    updated_at: "2026-05-13T00:00:00Z",
    ...overrides
  };
}
