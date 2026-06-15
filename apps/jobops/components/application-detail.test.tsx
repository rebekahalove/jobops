import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ApplicationDetail } from "./application-detail";
import type { TrackedApplication } from "./applications-tracker";

describe("Application detail", () => {
  it("renders compact primary facts, saved-job navigation, notes, and generated materials", () => {
    const html = renderToStaticMarkup(<ApplicationDetail applicationId="app-1" initialApplication={applicationFixture()} />);

    expect(html).toContain("Application detail");
    expect(html).toContain("Acme AI: Applied AI Engineer");
    expect(html).toContain("In process");
    expect(html).toContain("Recruiter screen scheduled.");
    expect(html).toContain("application-detail-primary-grid");
    expect(html).toContain("View saved job");
    expect(html).toContain('href="/jobs#saved-job-saved-job-1"');
    expect(html).not.toContain("Saved job saved-job-1; canonical job job-1");
    expect(html).not.toContain("canonical job job-1");
    expect(html).toContain("Application Materials");
    expect(html).toContain("Positioning Summary");
    expect(html).toContain("Focus the application on applied AI systems.");
    expect(html).toContain("Regenerate materials");
    expect(html).toContain('href="/applications"');
    expect(html).toContain("Back to Applications");
  });

  it("uses the mounted back link when rendered under /jobops", () => {
    const html = renderToStaticMarkup(
      <ApplicationDetail applicationId="app-1" initialApplication={applicationFixture()} workspaceBasePath="/jobops" />
    );

    expect(html).toContain('href="/jobops/applications"');
    expect(html).toContain('href="/jobops/jobs#saved-job-saved-job-1"');
  });

  it("folds lower-priority application metadata by default", () => {
    const html = renderToStaticMarkup(<ApplicationDetail applicationId="app-1" initialApplication={applicationFixture()} />);

    expect(html).toContain("<details");
    expect(html).toContain("application-detail-metadata");
    expect(html).toContain("<summary>More details</summary>");
    expect(html).toContain("Source");
    expect(html).toContain("Date applied");
    expect(html).toContain("Created");
    expect(html).toContain("Updated");
    expect(html).toContain("Archive");
    expect(html).not.toContain("<details open");
  });

  it("renders an empty materials state and archive action for an active application", () => {
    const html = renderToStaticMarkup(
      <ApplicationDetail applicationId="app-1" initialApplication={{ ...applicationFixture(), latest_material_bundle: null }} />
    );

    expect(html).toContain("No materials generated yet.");
    expect(html).toContain("Generate materials");
    expect(html).toContain("Archive");
    expect(html).not.toContain("Restore");
  });

  it("renders archived state and restore action for an archived application", () => {
    const html = renderToStaticMarkup(
      <ApplicationDetail
        applicationId="app-1"
        initialApplication={{
          ...applicationFixture(),
          archived_at: "2026-05-16T00:00:00Z",
          archived_reason: "Application archived by user.",
          archived_by_action: "user_archived_application"
        }}
      />
    );

    expect(html).toContain("Archived");
    expect(html.match(/application-status-archived/g)).toHaveLength(1);
    expect(html).toContain("Application archived by user.");
    expect(html).toContain("User archived application");
    expect(html).toContain("Restore");
    expect(html).not.toContain("Archive</button>");
  });

  it("shows the actual terminal status after restore instead of an applied bucket", () => {
    const html = renderToStaticMarkup(
      <ApplicationDetail applicationId="app-1" initialApplication={{ ...applicationFixture(), status: "rejected" }} />
    );

    expect(html).toContain("Rejected");
    expect(html).toContain("application-status-rejected");
    expect(html).not.toContain("application-status-applied");
    expect(html).not.toContain("application-status-archived");
    expect(html).toContain("Move back to Applied");
  });

  it("renders the terminal reset action for withdrawn archived applications", () => {
    const html = renderToStaticMarkup(
      <ApplicationDetail
        applicationId="app-1"
        initialApplication={{
          ...applicationFixture(),
          status: "withdrawn",
          archived_at: "2026-05-16T00:00:00Z",
          archived_by_action: "status_withdrawn",
          archived_reason: "Application marked withdrawn."
        }}
      />
    );

    expect(html).toContain("Withdrawn");
    expect(html).toContain("Restore");
    expect(html).toContain("Move back to Applied");
  });

  it("loads application detail from the id route and keeps action endpoints scoped to the application", async () => {
    const source = await readFile(new URL("./application-detail.tsx", import.meta.url), "utf-8");
    const pageSource = await readFile(new URL("../app/applications/[applicationId]/page.tsx", import.meta.url), "utf-8");
    const routeSource = await readFile(new URL("../app/api/applications/[applicationId]/route.ts", import.meta.url), "utf-8");

    expect(pageSource).toContain("<ApplicationDetail applicationId={applicationId}");
    expect(routeSource).toContain("`/v1/applications/${applicationId}`");
    expect(source).toContain("`${apiBasePath}/applications/${applicationId}`");
    expect(source).toContain("loadApplicationFromList(apiBasePath, applicationId)");
    expect(source).toContain("`${apiBasePath}/applications`");
    expect(source).toContain("`${apiBasePath}/applications/${application.id}/${action}`");
    expect(source).toContain('postApplicationAction("reopen"');
    expect(source).toContain("`${apiBasePath}/applications/${application.id}/materials/generate`");
    expect(source).toContain("window.dispatchEvent(new CustomEvent(\"jobops:jobs-updated\"))");
    expect(source).toContain("savedJobHref(application, workspaceBasePath)");
    expect(source).not.toContain("linkedJobLabel");
  });
});

function applicationFixture(): TrackedApplication {
  return {
    id: "app-1",
    candidate_profile_id: "profile-1",
    saved_job_id: "saved-job-1",
    company_id: "company-1",
    company_name: "Acme AI",
    job_title: "Applied AI Engineer",
    job_url: "https://example.com/jobs/applied-ai",
    apply_url: "https://example.com/jobs/applied-ai/apply",
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
    archived_reason: null,
    archived_by_action: null,
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
        }
      ]
    }
  };
}
