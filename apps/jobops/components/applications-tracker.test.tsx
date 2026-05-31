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
    expect(html).toContain("Inspect application page");
    expect(html).toContain("Generate materials");
    expect(html).not.toContain("Edit status");
  });

  it("renders extracted application requirements collapsed by default", () => {
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
            latest_job_page_extraction: {
              id: "extract-1",
              job_id: "job-1",
              extraction_status: "succeeded",
              platform: "generic",
              confidence: "high",
              fetched_at: "2026-05-14T00:00:00Z",
              source_url: "https://example.com/jobs/applied-ai",
              final_url: "https://example.com/jobs/applied-ai",
              required_materials: [{ type: "resume", label: "Resume", required: true, evidence: "Resume required" }],
              optional_materials: [{ type: "cover_letter", label: "Cover Letter", required: false, evidence: "Optional" }],
              application_fields: [
                {
                  fieldType: "textarea",
                  label: "Why this role?",
                  required: true,
                  normalizedKey: "why_this_role",
                  minLength: 20,
                  maxLength: 500,
                  limitSource: "html_attribute",
                  options: [],
                  acceptedFileTypes: [],
                  multiple: false,
                  evidence: "Why this role?"
                },
                {
                  fieldType: "select",
                  label: "Work authorization",
                  required: true,
                  normalizedKey: "work_authorization",
                  options: ["Yes", "No"],
                  acceptedFileTypes: [],
                  multiple: false,
                  evidence: "Work authorization"
                }
              ],
              screening_questions: [
                {
                  question: "Are you authorized to work in the United States?",
                  required: true,
                  answerType: "yes_no",
                  category: "work_authorization",
                  options: ["Yes", "No"],
                  evidence: "Are you authorized?"
                }
              ],
              detected_requirements: { resumeRequired: true },
              extraction_summary: "Detected application requirements.",
              warnings: [],
              error_message: null
            }
          }
        ]}
      />
    );

    expect(html).toContain("Application Requirements");
    expect(html).toContain("Resume · required");
    expect(html).toContain("Why this role? · required · max 500 · min 20");
    expect(html).toContain("options: Yes, No");
    expect(html).toContain("<details class=\"application-requirements\">");
    expect(html).not.toContain("<details class=\"application-requirements\" open=\"\"");
  });

  it("renders blocked extraction as a compact warning", () => {
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
            fit_summary: null,
            salary_text: null,
            remote_work_mode: "remote",
            employment_type: "Full-time",
            date_applied: null,
            status: "in_progress",
            notes: "",
            next_follow_up_date: null,
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z",
            latest_job_page_extraction: {
              id: "extract-1",
              job_id: "job-1",
              extraction_status: "blocked",
              platform: "generic",
              confidence: "low",
              fetched_at: "2026-05-14T00:00:00Z",
              source_url: "https://example.com/jobs/applied-ai",
              final_url: null,
              required_materials: [],
              optional_materials: [],
              application_fields: [],
              screening_questions: [],
              detected_requirements: {},
              extraction_summary: null,
              warnings: ["Blocked by bot protection."],
              error_message: null
            }
          }
        ]}
      />
    );

    expect(html).toContain("Could not inspect this page automatically.");
    expect(html).toContain("Blocked by bot protection.");
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
    expect(source).toContain("inspectApplicationPage(application)");
    expect(source).toContain('${apiBasePath}/applications/${application.id}/requirements/extract');
    expect(source).toContain("pendingMaterialsApplicationId");
    expect(source).toContain("pendingRequirementsApplicationId");
  });

  it("does not repurpose the separate Materials page", async () => {
    const source = await readFile(new URL("../app/materials/page.tsx", import.meta.url), "utf-8");

    expect(source).toContain("Materials");
    expect(source).not.toContain("applications/");
    expect(source).not.toContain("Generate materials");
  });
});
