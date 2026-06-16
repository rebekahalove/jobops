import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import CompaniesPage from "../app/companies/page";
import { CompaniesList } from "./companies-list";
import { CompanyDetail } from "./company-detail";
import MountedCompaniesPage from "../../portfolio/app/jobops/companies/page";

describe("Companies list", () => {
  it("renders the companies workspace", () => {
    const html = renderToStaticMarkup(<CompaniesPage />);

    expect(html).toContain("Company watchlist");
    expect(html).toContain("Saved companies");
    expect(html).toContain("No companies yet");
  });

  it("renders the real companies workspace in the mounted portfolio app", () => {
    const html = renderToStaticMarkup(<MountedCompaniesPage />);

    expect(html).toContain("Company watchlist");
    expect(html).toContain("Saved companies");
    expect(html).not.toContain("Coming soon");
  });

  it("renders model-derived companies with badges and external verification links", () => {
    const html = renderToStaticMarkup(
      <CompaniesList
        initialCompanies={[
          {
            id: "company-1",
            company_id: "canonical-company-1",
            name: "CivicActions",
            normalized_name: "civicactions",
            website_url: "https://civicactions.com",
            careers_url: "https://civicactions.com/careers",
            job_listings_url: "https://civicactions.com/jobs",
            greenhouse_board_token: "civicactions",
            ashby_board_url: null,
            lever_slug: null,
            description: "Digital services firm focused on civic technology.\n\nWorks with public-interest teams.",
            headquarters_city: null,
            headquarters_country: "United States",
            operating_countries: ["United States"],
            hiring_locations: ["Remote US", "Washington, DC"],
            remote_policy: "remote",
            role_fit_tags: ["Applied AI", "Senior Software Engineering"],
            mission_fit_tags: ["Civic tech", "Public-interest technology"],
            fit_reason: "Mission-aligned engineering work.",
            source_urls: ["https://civicactions.com/about"],
            source_summary: "Sources support mission and careers verification.",
            data_confidence: "high",
            discovery_query: "Find progressive politics companies.",
            search_queries_used: ["civic tech AI engineer jobs"],
            discovered_by: "mock",
            derivation_status: "model_derived",
            review_status: "new",
            notes: "",
            added_at: "2026-05-18T12:00:00Z",
            created_at: "2026-05-18T12:00:00Z",
            updated_at: "2026-05-18T12:00:00Z",
            last_checked_at: null,
            active_job_count: 3,
            saved_job_count: 1,
            application_count: 2,
            open_application_count: 1,
            can_sync_jobs: true,
            sync_providers: ["greenhouse"]
          }
        ]}
      />
    );

    expect(html).toContain("CivicActions");
    expect(html).toContain("company-provider-metadata");
    expect(html).toContain("company-description-panel");
    expect(html).toContain("Company Description");
    expect(html).toContain("Works with public-interest teams.");
    expect(html).toContain("company-card-meta");
    expect(html).toContain("company-card-actions");
    expect(html).toContain("New");
    expect(html).toContain("Model derived");
    expect(html).toContain("Remote US");
    expect(html).toContain("Washington, DC");
    expect(html).toContain("Added");
    expect(html).toContain("May 18, 2026");
    expect(html).toContain("Greenhouse");
    expect(html).toContain("civicactions");
    expect(html).toContain("3 active");
    expect(html).toContain("2 application");
    expect(html).toContain("Applied AI");
    expect(html).toContain("Public-interest technology");
    expect(html).toContain('href="/companies/company-1"');
    expect(html).toContain('href="https://civicactions.com/careers"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("does not render broken company URLs as links", () => {
    const html = renderToStaticMarkup(
      <CompaniesList
        initialCompanies={[
          {
            id: "company-1",
            company_id: "canonical-company-1",
            name: "Internal URL Co",
            normalized_name: "internal url co",
            website_url: "company:123",
            careers_url: null,
            job_listings_url: "not a url",
            description: null,
            headquarters_city: null,
            headquarters_country: null,
            operating_countries: [],
            hiring_locations: [],
            remote_policy: "unknown",
            role_fit_tags: [],
            mission_fit_tags: [],
            fit_reason: null,
            source_urls: ["job_listing:abc", "https://safe.example/source"],
            source_summary: null,
            discovery_query: null,
            search_queries_used: [],
            discovered_by: null,
            derivation_status: "user_entered",
            review_status: "reviewed",
            notes: "",
            created_at: "2026-05-18T12:00:00Z",
            updated_at: "2026-05-18T12:00:00Z",
            last_checked_at: null
          }
        ]}
      />
    );

    expect(html).not.toContain('href="company:123"');
    expect(html).not.toContain('href="job_listing:abc"');
    expect(html).toContain('href="https://safe.example/source"');
  });

  it("renders the company detail page with related jobs and applications", () => {
    const html = renderToStaticMarkup(
      <CompanyDetail
        companyId="company-1"
        initialCompany={{
          id: "company-1",
          company_id: "canonical-company-1",
          name: "Hightouch",
          normalized_name: "hightouch",
          website_url: "https://hightouch.com",
          careers_url: "https://hightouch.com/careers",
          job_listings_url: "https://boards.greenhouse.io/hightouch",
          greenhouse_board_token: "hightouch",
          ashby_board_url: null,
          lever_slug: null,
          description: "Customer data platform.",
          headquarters_city: "San Francisco",
          headquarters_country: "United States",
          operating_countries: ["United States"],
          hiring_locations: ["Remote US"],
          remote_policy: "remote",
          role_fit_tags: [],
          mission_fit_tags: [],
          fit_reason: null,
          source_urls: [],
          source_summary: null,
          data_confidence: "high",
          discovery_query: null,
          search_queries_used: [],
          discovered_by: "theirstack",
          derivation_status: "model_derived",
          review_status: "new",
          notes: "",
          created_at: "2026-05-18T12:00:00Z",
          updated_at: "2026-05-18T12:00:00Z",
          last_checked_at: null,
          active_job_count: 1,
          saved_job_count: 1,
          application_count: 1,
          open_application_count: 1,
          can_sync_jobs: true,
          sync_providers: ["greenhouse"],
          jobs: [
            {
              id: "job-1",
              saved_job_id: "saved-job-1",
              title: "AI Engineer",
              company_name: "Hightouch",
              job_url: "https://boards.greenhouse.io/hightouch/jobs/1",
              location: "Remote US",
              source_provider: "greenhouse",
              remote_work_mode: "remote",
              employment_type: "Full time",
              salary_text: "$150,000",
              full_description: "Build data products.",
              is_active: true,
              posting_date: "2026-06-01",
              saved_status: "saved",
              has_application: true,
              application_id: "app-1"
            }
          ],
          applications: [
            {
              id: "app-1",
              saved_job_id: "saved-job-1",
              company_id: "canonical-company-1",
              company_name: "Hightouch",
              job_title: "AI Engineer",
              job_url: "https://boards.greenhouse.io/hightouch/jobs/1",
              location: "Remote US",
              source: "greenhouse",
              status: "started",
              created_at: "2026-06-02T12:00:00Z"
            }
          ]
        }}
      />
    );

    expect(html).toContain("Company jobs");
    expect(html).toContain("AI Engineer");
    expect(html).toContain("View Application");
    expect(html).toContain("Company applications");
    expect(html).toContain("Build data products.");
  });

  it("refreshes when command-center company discovery completes", async () => {
    const source = await readFile(new URL("./companies-list.tsx", import.meta.url), "utf-8");

    expect(source).toContain('window.addEventListener("jobops:companies-updated", loadCompanies)');
    expect(source).toContain('window.removeEventListener("jobops:companies-updated", loadCompanies)');
  });
});
