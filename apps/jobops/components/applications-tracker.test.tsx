import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ApplicationsPage from "../app/applications/page";
import { ApplicationsTracker } from "./applications-tracker";

describe("Applications tracker", () => {
  it("renders the application pipeline without the old manual form", () => {
    const html = renderToStaticMarkup(<ApplicationsPage />);

    expect(html).toContain("Application pipeline");
    expect(html).toContain("Click Apply on a saved job to start an application.");
    expect(html).not.toContain("Manual tracker MVP");
    expect(html).not.toContain("Add application");
    expect(html).not.toContain("Save application");
  });

  it("renders compact application cards with role, company, status, links, and mark-applied action", () => {
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
            status: "in_progress",
            notes: "Recruiter screen scheduled.",
            next_follow_up_date: "2026-05-20",
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain("Applications");
    expect(html).toContain("Applied AI Engineer");
    expect(html).toContain("Acme AI");
    expect(html).toContain("In progress");
    expect(html).toContain('href="https://example.com/jobs/applied-ai"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain("Remote");
    expect(html).toContain("manual");
    expect(html).toContain("Full-time");
    expect(html).toContain("USD 150,000-180,000");
    expect(html).toContain("05/10/2026");
    expect(html).toContain("05/20/2026");
    expect(html).toContain("Recruiter screen scheduled.");
    expect(html).toContain("Strong platform fit.");
    expect(html).toContain("Mark applied");
    expect(html).toContain("Generate materials");
    expect(html).not.toContain("Edit status");
  });

  it("renders generated materials under a collapsed application-card section", () => {
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
            status: "in_progress",
            notes: "Recruiter screen scheduled.",
            next_follow_up_date: "2026-05-20",
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

    expect(html).toContain("Application Materials");
    expect(html).toContain("Positioning Summary");
    expect(html).toContain("Cover Letter Draft");
    expect(html).toContain("Regenerate materials");
    expect(html).toContain("<details class=\"application-materials\">");
    expect(html).not.toContain("<details class=\"application-materials\" open=\"\"");
  });

  it("refreshes on application updates and highlights URL-selected applications", async () => {
    const source = await readFile(new URL("./applications-tracker.tsx", import.meta.url), "utf-8");

    expect(source).toContain('window.addEventListener("jobops:applications-updated", loadApplications)');
    expect(source).toContain('window.removeEventListener("jobops:applications-updated", loadApplications)');
    expect(source).toContain('new URLSearchParams(window.location.search).get("applicationId")');
    expect(source).toContain("scrollIntoView");
    expect(source).toContain('body: JSON.stringify({ status: "applied" })');
    expect(source).toContain("generateMaterials(application)");
    expect(source).toContain('${apiBasePath}/applications/${application.id}/materials/generate');
    expect(source).toContain("pendingMaterialsApplicationId");
  });

  it("does not repurpose the separate Materials page", async () => {
    const source = await readFile(new URL("../app/materials/page.tsx", import.meta.url), "utf-8");

    expect(source).toContain("Materials");
    expect(source).not.toContain("applications/");
    expect(source).not.toContain("Generate materials");
  });
});
