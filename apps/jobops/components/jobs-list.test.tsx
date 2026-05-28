import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import JobsPage from "../app/jobs/page";
import { JobsList } from "./jobs-list";

describe("Jobs list", () => {
  it("renders the jobs workspace empty state", () => {
    const html = renderToStaticMarkup(<JobsPage />);

    expect(html).toContain("Saved job search");
    expect(html).toContain("Saved jobs");
    expect(html).toContain("No saved jobs yet");
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
            location: "Remote US",
            remote_work_mode: "remote",
            employment_type: "Full-time",
            salary_text: "$150k-$180k",
            description_excerpt: "Build applied AI workflows for civic data products.",
            fit_summary: "Matches applied AI and platform engineering goals.",
            user_notes: null,
            status: "saved",
            added_at: "2026-05-28T12:00:00Z",
            archived_at: null,
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
    expect(html).toContain("$150k-$180k");
    expect(html).toContain("May 28, 2026");
    expect(html).toContain("05/20/2026");
    expect(html).toContain("Matches applied AI and platform engineering goals.");
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

  it("refreshes when command-center job discovery completes", async () => {
    const source = await readFile(new URL("./jobs-list.tsx", import.meta.url), "utf-8");
    const commandCenterSource = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");

    expect(source).toContain('window.addEventListener("jobops:jobs-updated", loadJobs)');
    expect(source).toContain('window.removeEventListener("jobops:jobs-updated", loadJobs)');
    expect(commandCenterSource).toContain('action.type === "job_discovery"');
    expect(commandCenterSource).toContain('window.dispatchEvent(new CustomEvent("jobops:jobs-updated"');
  });
});
