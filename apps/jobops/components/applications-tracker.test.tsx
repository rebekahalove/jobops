import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ApplicationsPage from "../app/applications/page";
import {
  ApplicationsTracker,
  applicationBucket,
  buildApplicationBucketCounts,
  sortApplicationsForBucket,
  type TrackedApplication
} from "./applications-tracker";

describe("Applications tracker", () => {
  it("renders the application pipeline without the old manual form", () => {
    const html = renderToStaticMarkup(<ApplicationsPage />);

    expect(html).toContain("Application pipeline");
    expect(html).toContain("No started applications.");
    expect(html).toContain("Start an application from a saved job and it will appear here.");
    expect(html).not.toContain("Manual tracker MVP");
    expect(html).not.toContain("Add application");
    expect(html).not.toContain("Save application");
  });

  it("renders compact application cards with role, company, status, links, and view action", () => {
    const html = renderToStaticMarkup(
      <ApplicationsTracker
        initialApplications={[
          {
            id: "app-1",
            company_name: "Acme AI",
            job_title: "Applied AI Engineer",
            job_url: "https://example.com/jobs/applied-ai",
            location: "Remote",
            source: "manual",
            source_provider: "greenhouse",
            posting_date: "2026-05-10",
            fit_summary: "Strong platform fit.",
            salary_text: "USD 150,000-180,000",
            remote_work_mode: "remote",
            employment_type: "Full-time",
            date_applied: null,
            status: "in_process",
            notes: "Recruiter screen scheduled.",
            next_follow_up_date: "2026-05-20",
            archived_at: null,
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain("Applications");
    expect(html).toContain("Applied AI Engineer");
    expect(html).toContain("Acme AI");
    expect(html).toContain("In Process");
    expect(html).toContain('href="https://example.com/jobs/applied-ai"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain("Remote");
    expect(html).toContain("manual");
    expect(html).toContain("Full-time");
    expect(html).toContain("USD 150,000-180,000");
    expect(html).toContain("05/10/2026");
    expect(html).toContain("Recruiter screen scheduled.");
    expect(html).toContain("Strong platform fit.");
    expect(html).toContain("Mark applied");
    expect(html).toContain("Archive");
    expect(html).toContain('href="/applications/app-1"');
    expect(html).toContain("View Application");
    expect(html).not.toContain("Reject");
    expect(html).not.toContain("Withdraw");
    expect(html).not.toContain("Edit status");
    expect(html).not.toContain("Generate materials");
    expect(html).not.toContain("Follow-up");
    expect(html).not.toContain("<dt>Archive</dt>");

    const fitIndex = html.indexOf("Strong platform fit.");
    const jobPostIndex = html.indexOf("Job post");
    const postedIndex = html.indexOf("<dt>Posted</dt>");
    const locationIndex = html.indexOf("<dt>Location</dt>");
    const compensationIndex = html.indexOf("<dt>Compensation</dt>");
    const employmentIndex = html.indexOf("<dt>Employment</dt>");
    const sourceIndex = html.indexOf("<dt>Source</dt>");
    const createdIndex = html.indexOf("<dt>Created</dt>");
    const appliedIndex = html.indexOf("<dt>Applied</dt>");
    const statusIndex = html.indexOf("<dt>Status</dt>");
    const viewIndex = html.indexOf("View Application");
    const markAppliedIndex = html.indexOf("Mark applied");
    const archiveIndex = html.indexOf("Archive", markAppliedIndex);

    expect(fitIndex).toBeLessThan(jobPostIndex);
    expect(postedIndex).toBeLessThan(locationIndex);
    expect(locationIndex).toBeLessThan(compensationIndex);
    expect(compensationIndex).toBeLessThan(employmentIndex);
    expect(sourceIndex).toBeLessThan(createdIndex);
    expect(createdIndex).toBeLessThan(appliedIndex);
    expect(appliedIndex).toBeLessThan(statusIndex);
    expect(viewIndex).toBeLessThan(markAppliedIndex);
    expect(markAppliedIndex).toBeLessThan(archiveIndex);
  });

  it("routes application cards through the mounted workspace base path when provided", () => {
    const html = renderToStaticMarkup(
      <ApplicationsTracker
        workspaceBasePath="/jobops"
        initialApplications={[
          {
            id: "app-1",
            company_name: "Acme AI",
            job_title: "Applied AI Engineer",
            job_url: null,
            location: null,
            source: null,
            date_applied: null,
            status: "in_process",
            notes: "",
            next_follow_up_date: null,
            archived_at: null,
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain('href="/jobops/applications/app-1"');
  });

  it("shows reject and withdraw only for applied applications", () => {
    const html = renderToStaticMarkup(
      <ApplicationsTracker
        initialApplications={[
          {
            id: "app-1",
            company_name: "Acme AI",
            job_title: "Applied AI Engineer",
            job_url: null,
            location: null,
            source: null,
            date_applied: "2026-05-13",
            status: "applied",
            notes: "",
            next_follow_up_date: null,
            archived_at: null,
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain("Applied AI Engineer");
    expect(html).toContain("Reject");
    expect(html).toContain("Withdraw");
    expect(html).not.toContain("Mark applied");
  });

  it("renders restored terminal statuses in the applied bucket and archived applications with restore", () => {
    const restoredHtml = renderToStaticMarkup(
      <ApplicationsTracker
        initialApplications={[
          {
            id: "app-1",
            company_name: "Acme AI",
            job_title: "Rejected Engineer",
            job_url: null,
            location: null,
            source: null,
            date_applied: null,
            status: "rejected",
            notes: "",
            next_follow_up_date: null,
            archived_at: null,
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z"
          }
        ]}
      />
    );
    const archivedHtml = renderToStaticMarkup(
      <ApplicationsTracker
        initialApplications={[
          {
            id: "app-2",
            company_name: "Beta AI",
            job_title: "Archived Engineer",
            job_url: null,
            location: null,
            source: null,
            date_applied: null,
            status: "withdrawn",
            notes: "",
            next_follow_up_date: null,
            archived_at: "2026-05-14T00:00:00Z",
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-14T00:00:00Z"
          }
        ]}
      />
    );

    expect(restoredHtml).toContain("Rejected Engineer");
    expect(restoredHtml).toContain("Applied");
    expect(restoredHtml).toContain("Rejected");
    expect(archivedHtml).toContain("Archived Engineer");
    expect(archivedHtml).toContain("Archived");
    expect(archivedHtml).toContain("Withdrawn");
    expect(archivedHtml).toContain("Restore");
  });

  it("keeps generated materials compact on application cards", () => {
    const html = renderToStaticMarkup(
      <ApplicationsTracker
        initialApplications={[
          {
            id: "app-1",
            company_name: "Acme AI",
            job_title: "Applied AI Engineer",
            job_url: "https://example.com/jobs/applied-ai",
            location: "Remote",
            source: "manual",
            source_provider: "greenhouse",
            posting_date: "2026-05-10",
            fit_summary: "Strong platform fit.",
            salary_text: "USD 150,000-180,000",
            remote_work_mode: "remote",
            employment_type: "Full-time",
            date_applied: null,
            status: "in_process",
            notes: "Recruiter screen scheduled.",
            next_follow_up_date: "2026-05-20",
            archived_at: null,
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z",
            latest_material_bundle: {
              id: "bundle-1",
              application_id: "app-1",
              candidate_profile_id: "profile-1",
              status: "generated",
              model_provider: "mock",
              model_name: "mock-default",
              created_at: "2026-05-14T00:00:00Z",
              updated_at: "2026-05-14T00:00:00Z",
              items: [
                {
                  id: "item-1",
                  bundle_id: "bundle-1",
                  material_type: "positioning_summary",
                  title: "Positioning Summary",
                  content: "Focus the application on applied AI systems.",
                  content_format: "markdown",
                  sort_order: 0,
                  created_at: "2026-05-14T00:00:00Z",
                  updated_at: "2026-05-14T00:00:00Z"
                },
                {
                  id: "item-2",
                  bundle_id: "bundle-1",
                  material_type: "cover_letter_draft",
                  title: "Cover Letter Draft",
                  content: "Dear Acme AI team,",
                  content_format: "markdown",
                  sort_order: 1,
                  created_at: "2026-05-14T00:00:00Z",
                  updated_at: "2026-05-14T00:00:00Z"
                }
              ]
            }
          }
        ]}
      />
    );

    expect(html).toContain("Materials ready");
    expect(html).toContain('href="/applications/app-1"');
    expect(html).not.toContain("Regenerate materials");
    expect(html).not.toContain("Positioning Summary");
    expect(html).not.toContain("Cover Letter Draft");
    expect(html).not.toContain("<details class=\"application-materials\">");
  });

  it("refreshes on application updates and highlights URL-selected applications", async () => {
    const source = await readFile(new URL("./applications-tracker.tsx", import.meta.url), "utf-8");

    expect(source).toContain('window.addEventListener("jobops:applications-updated", loadApplications)');
    expect(source).toContain('window.removeEventListener("jobops:applications-updated", loadApplications)');
    expect(source).toContain('new URLSearchParams(window.location.search).get("applicationId")');
    expect(source).toContain("scrollIntoView");
    expect(source).toContain('body: JSON.stringify({ status: "applied" })');
    expect(source).toContain('${apiBasePath}/applications/${application.id}/${action}');
    expect(source).toContain('postApplicationAction(application, "reject"');
    expect(source).toContain('postApplicationAction(application, "withdraw"');
    expect(source).not.toContain("generateMaterials(application)");
    expect(source).not.toContain('${apiBasePath}/applications/${application.id}/materials/generate');
    expect(source).not.toContain("pendingMaterialsApplicationId");
  });

  it("does not repurpose the separate Materials page", async () => {
    const source = await readFile(new URL("../app/materials/page.tsx", import.meta.url), "utf-8");

    expect(source).toContain("Materials");
    expect(source).not.toContain("applications/");
    expect(source).not.toContain("Generate materials");
  });

  it("renders tabs with counts for each application queue", () => {
    const html = renderToStaticMarkup(
      <ApplicationsTracker
        initialApplications={[
          applicationFixture({ id: "app-started", status: "saved", job_title: "Started Role" }),
          applicationFixture({ id: "app-applied", status: "rejected", job_title: "Applied Role" }),
          applicationFixture({ id: "app-process", status: "interviewing", job_title: "Interviewing Role" }),
          applicationFixture({ id: "app-archived", archived_at: "2026-05-18T00:00:00Z", status: "offer", job_title: "Archived Role" })
        ]}
      />
    );

    expect(html).toContain("Started");
    expect(html).toContain("Applied");
    expect(html).toContain("In Process");
    expect(html).toContain("Archived");
    expect(html).toContain("<strong>1</strong>");
  });

  it("buckets applications with archived as an overlay", () => {
    const applications = [
      applicationFixture({ status: "saved" }),
      applicationFixture({ id: "started", status: "started" }),
      applicationFixture({ id: "in-process", status: "in_process" }),
      applicationFixture({ id: "in-progress", status: "in_progress" }),
      applicationFixture({ id: "interviewing", status: "interviewing" }),
      applicationFixture({ id: "offer", status: "offer" }),
      applicationFixture({ id: "applied", status: "applied" }),
      applicationFixture({ id: "rejected", status: "rejected" }),
      applicationFixture({ id: "withdrawn", status: "withdrawn" }),
      applicationFixture({ id: "closed", status: "closed" }),
      applicationFixture({ id: "archived", archived_at: "2026-05-18T00:00:00Z", status: "rejected" })
    ];

    expect(applications.map(applicationBucket)).toEqual([
      "started",
      "started",
      "in-process",
      "in-process",
      "in-process",
      "in-process",
      "applied",
      "applied",
      "applied",
      "applied",
      "archived"
    ]);
    expect(buildApplicationBucketCounts(applications)).toEqual({ started: 2, applied: 4, "in-process": 4, archived: 1 });
  });

  it("sorts application queues by their requested dates", () => {
    const applications = [
      applicationFixture({ id: "older", date_applied: "2026-05-10", created_at: "2026-05-09T00:00:00Z", updated_at: "2026-05-11T00:00:00Z" }),
      applicationFixture({ id: "newer", date_applied: "2026-05-12", created_at: "2026-05-08T00:00:00Z", updated_at: "2026-05-14T00:00:00Z" })
    ];

    expect(sortApplicationsForBucket(applications, "applied").map((application) => application.id)).toEqual(["newer", "older"]);
  });
});

function applicationFixture(overrides: Partial<TrackedApplication> = {}): TrackedApplication {
  return {
    id: "app-1",
    company_name: "Acme AI",
    job_title: "Applied AI Engineer",
    job_url: null,
    location: null,
    source: null,
    date_applied: null,
    status: "applied",
    notes: "",
    next_follow_up_date: null,
    archived_at: null,
    created_at: "2026-05-13T00:00:00Z",
    updated_at: "2026-05-13T00:00:00Z",
    ...overrides
  };
}
