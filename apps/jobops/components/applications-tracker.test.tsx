import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ApplicationsPage from "../app/applications/page";
import { ApplicationsTracker } from "./applications-tracker";

describe("Applications tracker", () => {
  it("renders the manual application form", () => {
    const html = renderToStaticMarkup(<ApplicationsPage />);

    expect(html).toContain("Manual tracker MVP");
    expect(html).toContain("Add application");
    expect(html).toContain("Company");
    expect(html).toContain("Job title");
    expect(html).toContain("Next follow-up");
    expect(html).toContain("Save application");
  });

  it("renders saved applications with status, follow-up, notes, and status editing", () => {
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
            date_applied: "2026-05-13",
            status: "interviewing",
            notes: "Recruiter screen scheduled.",
            next_follow_up_date: "2026-05-20",
            created_at: "2026-05-13T00:00:00Z",
            updated_at: "2026-05-13T00:00:00Z"
          }
        ]}
      />
    );

    expect(html).toContain("Saved applications");
    expect(html).toContain("Applied AI Engineer");
    expect(html).toContain("Acme AI");
    expect(html).toContain("Interviewing");
    expect(html).toContain("05/20/2026");
    expect(html).toContain("Recruiter screen scheduled.");
    expect(html).toContain("Edit status");
  });
});
