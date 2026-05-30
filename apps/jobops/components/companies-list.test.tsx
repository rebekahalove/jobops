import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import CompaniesPage from "../app/companies/page";
import { CompaniesList } from "./companies-list";

describe("Companies list", () => {
  it("renders the companies workspace", () => {
    const html = renderToStaticMarkup(<CompaniesPage />);

    expect(html).toContain("Company watchlist");
    expect(html).toContain("Saved companies");
    expect(html).toContain("No companies yet");
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
            description: "Digital services firm focused on civic technology.",
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
            discovery_query: "Find progressive politics companies.",
            search_queries_used: ["civic tech AI engineer jobs"],
            discovered_by: "mock",
            derivation_status: "model_derived",
            review_status: "new",
            notes: "",
            added_at: "2026-05-18T12:00:00Z",
            created_at: "2026-05-18T12:00:00Z",
            updated_at: "2026-05-18T12:00:00Z",
            last_checked_at: null
          }
        ]}
      />
    );

    expect(html).toContain("CivicActions");
    expect(html).toContain("New");
    expect(html).toContain("Model derived");
    expect(html).toContain("Remote US, Washington, DC");
    expect(html).toContain("Added");
    expect(html).toContain("May 18, 2026");
    expect(html).toContain("Applied AI");
    expect(html).toContain("Public-interest technology");
    expect(html).toContain('href="https://civicactions.com/careers"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("refreshes when command-center company discovery completes", async () => {
    const source = await readFile(new URL("./companies-list.tsx", import.meta.url), "utf-8");

    expect(source).toContain('window.addEventListener("jobops:companies-updated", loadCompanies)');
    expect(source).toContain('window.removeEventListener("jobops:companies-updated", loadCompanies)');
  });
});
