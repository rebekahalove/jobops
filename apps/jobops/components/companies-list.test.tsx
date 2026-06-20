import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import CompaniesPage from "../app/companies/page";
import JobsPage from "../app/jobs/page";
import { CompanyDiscoveryDiagnostics } from "./company-discovery-diagnostics";
import { buildCompanyBucketCounts, CompaniesList, companyBucket, defaultCompanyBucket, type TrackedCompany } from "./companies-list";
import { CompanyDetail } from "./company-detail";
import MountedCompaniesPage from "../../portfolio/app/jobops/companies/page";

describe("Companies list", () => {
  it("renders the companies workspace", () => {
    const html = renderToStaticMarkup(<CompaniesPage />);

    expect(html).toContain("Company watchlist");
    expect(html).toContain("Company discovery diagnostics");
    expect(html).toContain("Saved companies");
    expect(html).toContain("No watched companies yet");
    expect(html).not.toContain("id=\"job-discovery-diagnostics-title\"");
  });

  it("renders the real companies workspace in the mounted portfolio app", () => {
    const html = renderToStaticMarkup(<MountedCompaniesPage />);

    expect(html).toContain("Company watchlist");
    expect(html).toContain("Saved companies");
    expect(html).not.toContain("Coming soon");
  });

  it("mounts the company-detail add-to-jobs-list proxy route in the portfolio app", async () => {
    const source = await readFile(
      new URL("../../portfolio/app/jobops/api/jobs/from-listing/[jobListingId]/route.ts", import.meta.url),
      "utf-8"
    );

    expect(source).toContain('export { POST } from "../../../../../../../jobops/app/api/jobs/from-listing/[jobListingId]/route"');
    expect(source).toContain('export const runtime = "nodejs"');
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
    expect(html).toContain("Discovery source");
    expect(html).toContain("Model-grounded discovery");
    expect(html).toContain("Data source");
    expect(html).toContain("civicactions.com");
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
    expect(html).toContain('class="company-card-title-link" href="/companies/company-1"');
    expect(html).toContain('class="company-card-site-link" href="https://civicactions.com/"');
    expect(html).toContain("<summary>Metadata</summary>");
    expect(html).not.toContain("<dt>Website</dt>");
    expect(html).not.toContain("<dt>Careers</dt>");
    expect(html).not.toContain("<dt>Job board</dt>");
    expect(html).not.toContain("View Company");
    expect(html).not.toContain('href="https://civicactions.com/jobs"');
    expect(html).toContain('aria-label="Greenhouse"');
    expect(html).toContain(">GH</span>");
    expect(html).toContain("civicactions");
    expect(html).toContain("<h3>Jobs</h3>");
    expect(html).toContain("<dd>3</dd>");
    expect(html).toContain("<dt>active</dt>");
    expect(html).toContain("<dd>1</dd>");
    expect(html).toContain("<dt>saved</dt>");
    expect(html).toContain("<dd>2</dd>");
    expect(html).toContain("<dt>applied</dt>");
    expect(html).toContain("<dt>open</dt>");
    expect(html).toContain("Applied AI");
    expect(html).toContain("Public-interest technology");
    expect(html).toContain('href="/companies/company-1"');
    expect(html).toContain('href="https://civicactions.com/careers"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("renders company card source labels for TheirStack and user-entered companies", () => {
    const html = renderToStaticMarkup(
      <CompaniesList
        initialCompanies={[
          companyFixture({
            id: "theirstack-company",
            name: "Hightouch",
            discovered_by: "theirstack",
            discoverySource: "theirstack",
            discoverySourceLabel: "TheirStack",
            dataOriginSource: "theirstack",
            dataOriginSourceType: "provider",
            dataOriginSourceLabel: "TheirStack company search",
            greenhouse_board_token: "hightouch",
            provider_grounding_metadata_summary: {
              atsInference: {
                greenhouseBoardToken: "hightouch"
              }
            }
          }),
          companyFixture({
            id: "user-company",
            name: "User Entered Co",
            derivation_status: "user_entered",
            discoverySource: "user_entered",
            discoverySourceLabel: "User-entered",
            dataOriginSource: "user",
            dataOriginSourceType: "user",
            dataOriginSourceLabel: "User-entered"
          })
        ]}
      />
    );

    expect(html).toContain("TheirStack");
    expect(html).toContain("TheirStack company search");
    expect(html).toContain("ATS inferred");
    expect(html).toContain("Greenhouse");
    expect(html).toContain("User-entered");
  });

  it("renders company diagnostics and keeps job diagnostics on the jobs page", () => {
    const companyHtml = renderToStaticMarkup(
      <CompanyDiscoveryDiagnostics
        initialRun={{
          id: "company-run-1",
          status: "completed",
          sourcePath: "model_grounded_company_discovery",
          sourceProvider: "gemini",
          searchGroundingEnabled: true,
          savedCompanyCount: 4,
          linkedCompanyCount: 4,
          duplicateCompanyCount: 0,
          skippedCompanyCount: 0,
          theirStack: {
            checked: true,
            enabled: true,
            used: false,
            skippedReason: "planner_chose_model_grounded"
          },
          firstPartySync: {
            attempted: false,
            providers: []
          },
          providerDiagnostics: [
            {
              stage: "company_source",
              provider: "gemini",
              status: "completed",
              label: "Gemini model-grounded company discovery",
              requestSummary: { searchGroundingEnabled: true },
              resultSummary: { savedCompanyCount: 4 }
            }
          ],
          companies: [
            {
              name: "CivicActions",
              discoverySource: "model_grounded",
              dataOriginSource: "https://civicactions.com/careers",
              dataOriginSourceType: "careers_url"
            }
          ]
        }}
      />
    );
    const jobsHtml = renderToStaticMarkup(<JobsPage />);

    expect(companyHtml).toContain("Company discovery diagnostics");
    expect(companyHtml).toContain("Gemini model-grounded discovery saved 4 companies");
    expect(companyHtml).toContain("Source timeline / Provider calls");
    expect(companyHtml).toContain("Gemini model-grounded company discovery");
    expect(companyHtml).toContain("Search Grounding Enabled: Yes");
    expect(companyHtml).toContain("TheirStack");
    expect(companyHtml).toContain("Planner chose model grounded");
    expect(companyHtml).not.toContain("id=\"job-discovery-diagnostics-title\"");
    expect(jobsHtml).toContain("id=\"job-discovery-diagnostics-title\"");
    expect(jobsHtml).not.toContain("Company discovery diagnostics");
  });

  it("keeps the provider-call section visible while company diagnostics are pending", async () => {
    const source = await readFile(new URL("./company-discovery-diagnostics.tsx", import.meta.url), "utf-8");

    expect(source).toContain("Waiting for router/source diagnostics");
    expect(source).toContain("Waiting for provider-call diagnostics for run");
    expect(source).toContain("COMPANY_DISCOVERY_DIAGNOSTICS_POLL_INTERVAL_MS");
    expect(source).toContain("encodeURIComponent(runId)");
    expect(source).toContain("companyDiscoveryRunIdFromEventDetail(detail)");
    expect(source).toContain("detail.diagnosticsId");
    expect(source).toContain("loadIfActive({ clearWhenMissing: true })");
    expect(source).toContain("loadIfActive({ clearWhenMissing: false, ignorePendingStartTime: true");
    expect(source).toContain("ignorePendingStartTime: true");
    expect(source).toContain("const effectivePendingRun = run ? null : pendingRun");
    expect(source).toContain('window.addEventListener("jobops:company-discovery-updated", handleDiscoveryUpdated)');
    expect(source).toContain("setLatestRun(detail.diagnostics)");
    expect(source).toContain("TERMINAL_COMPANY_DISCOVERY_STATUSES.has(latestRun.status)");
    expect(source).toContain("latestRun?.id");
    expect(source).toContain("!runId && pendingStartedAtRef.current");
    expect(source).toContain("setPendingRun(null)");
    expect(source).toContain("pendingStartedAtRef.current = companyDiscoveryRunId ? null : startedAt");
    expect(source).toContain("Source timeline / Provider calls");
    expect(source).not.toContain("expectedDecision");
    expect(source).not.toContain("expectedProviders");
    expect(source).not.toContain("expectedCounts");
    expect(source).not.toContain("PendingCompanyProviderTimeline");
    expect(source).not.toContain("TheirStack company search or model-grounded discovery");
  });

  it("renders company provider diagnostics for TheirStack and first-party sync rows", () => {
    const html = renderToStaticMarkup(
      <CompanyDiscoveryDiagnostics
        initialRun={{
          id: "company-run-2",
          status: "completed",
          sourcePath: "theirstack_company_enrichment",
          sourceProvider: "theirstack",
          savedCompanyCount: 2,
          linkedCompanyCount: 2,
          duplicateCompanyCount: 0,
          skippedCompanyCount: 1,
          theirStack: {
            checked: true,
            enabled: true,
            used: true,
            requestedPages: 1,
            fetchedPages: 1,
            rawCompanyCount: 5,
            normalizedCompanyCount: 4,
            linkedCandidateCompanyCount: 2,
            requestShape: { job_filters: "<present>", limit: 25, max_pages: 1 }
          },
          firstPartySync: {
            attempted: true,
            providers: ["greenhouse", "ashby"],
            greenhouseBoardsSelected: ["hightouch"],
            greenhouseBoardsSynced: ["hightouch"],
            ashbyBoardsSelected: ["https://jobs.ashbyhq.com/ashbyco"],
            ashbyBoardsSynced: ["https://jobs.ashbyhq.com/ashbyco"],
            completedCount: 2,
            failedCount: 0,
            normalizedJobCount: 7
          },
          providerDiagnostics: [
            {
              stage: "company_source",
              provider: "theirstack",
              status: "completed",
              label: "TheirStack company search",
              requestSummary: { requestedPages: 1, requestShape: { job_filters: "<present>", limit: 25 } },
              resultSummary: { rawCompanyCount: 5, normalizedCompanyCount: 4, linkedCandidateCompanyCount: 2 }
            },
            {
              stage: "first_party_sync",
              provider: "greenhouse",
              status: "completed",
              label: "Greenhouse board sync",
              resultSummary: { rawResultCount: 3, normalizedJobCount: 3 }
            },
            {
              stage: "first_party_sync",
              provider: "ashby",
              status: "completed",
              label: "Ashby board sync",
              resultSummary: { rawResultCount: 4, normalizedJobCount: 4 }
            }
          ],
          companies: []
        }}
      />
    );

    expect(html).toContain("<details open=\"\"");
    expect(html).toContain("Source timeline / Provider calls");
    expect(html).toContain("TheirStack company search");
    expect(html).toContain("Raw Company Count: 5");
    expect(html).toContain("Greenhouse board sync");
    expect(html).toContain("Ashby board sync");
  });

  it("renders the legacy company diagnostics message without blanking the panel", () => {
    const html = renderToStaticMarkup(
      <CompanyDiscoveryDiagnostics
        initialRun={{
          id: "company-run-legacy",
          status: "completed",
          sourcePath: "unknown",
          sourceProvider: "unknown",
          savedCompanyCount: 0,
          linkedCompanyCount: 0,
          duplicateCompanyCount: 0,
          skippedCompanyCount: 0,
          providerDiagnostics: [],
          diagnosticMessages: [
            "This command was logged before company discovery diagnostics were added. Run company discovery again to populate detailed diagnostics."
          ],
          companies: []
        }}
      />
    );

    expect(html).toContain("Company discovery diagnostics");
    expect(html).toContain("This command was logged before company discovery diagnostics were added");
  });

  it("buckets watched, avoided, and archived companies into exactly one tab", () => {
    const watched = companyFixture({ id: "watch", review_status: "new" });
    const avoided = companyFixture({ id: "avoid", review_status: "avoided" });
    const archivedAvoided = companyFixture({ id: "archived", review_status: "avoided", archived_at: "2026-06-01T12:00:00Z" });

    expect(companyBucket(watched)).toBe("watch");
    expect(companyBucket(avoided)).toBe("avoid");
    expect(companyBucket(archivedAvoided)).toBe("archived");
    expect(buildCompanyBucketCounts([watched, avoided, archivedAvoided])).toEqual({
      watch: 1,
      avoid: 1,
      archived: 1
    });
  });

  it("chooses watch list by default unless it is empty", () => {
    expect(defaultCompanyBucket([])).toBe("watch");
    expect(defaultCompanyBucket([companyFixture({ review_status: "avoided" })])).toBe("avoid");
    expect(defaultCompanyBucket([companyFixture({ archived_at: "2026-06-01T12:00:00Z" })])).toBe("archived");
    expect(defaultCompanyBucket([companyFixture({ review_status: "new" }), companyFixture({ review_status: "avoided" })])).toBe("watch");
  });

  it("renders company status tabs with selected-tab counts and specific empty states", async () => {
    const emptyHtml = renderToStaticMarkup(<CompaniesList />);
    const source = await readFile(new URL("./companies-list.tsx", import.meta.url), "utf-8");

    expect(emptyHtml).toContain("queue-tabs");
    expect(emptyHtml).toContain("Watch list");
    expect(emptyHtml).toContain("Avoid list");
    expect(emptyHtml).toContain("Archived");
    expect(emptyHtml).toContain("No watched companies yet");
    expect(source).toContain("No avoided companies");
    expect(source).toContain("No archived companies");
  });

  it("renders avoid and archive action buttons for active companies", () => {
    const html = renderToStaticMarkup(<CompaniesList initialCompanies={[companyFixture({ id: "company-1" })]} />);

    expect(html).toContain("Mark Avoid");
    expect(html).toContain("Archive");
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
    expect(html).not.toContain("No company site");
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
              job_listing_id: "job-1",
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
              saved_status: "new",
              has_application: false,
              application_id: null
            },
            {
              id: "job-2",
              saved_job_id: null,
              job_listing_id: "job-2",
              title: "Unsaved Data Engineer",
              company_name: "Hightouch",
              job_url: "https://boards.greenhouse.io/hightouch/jobs/2",
              location: "Remote US",
              source_provider: "greenhouse",
              remote_work_mode: "remote",
              employment_type: "Full time",
              salary_text: "$140,000",
              full_description: "Build data pipelines.",
              is_active: true,
              posting_date: "2026-06-02",
              saved_status: null,
              has_application: false,
              application_id: null
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
    expect(html).toContain("job-card");
    expect(html).toContain("job-primary-metadata");
    expect(html).toContain("AI Engineer");
    expect(html).toContain("Favorite");
    expect(html).toContain("Apply");
    expect(html).toContain("Archive");
    expect(html).toContain("Unsaved Data Engineer");
    expect(html).toContain("Add to jobs list");
    expect(html).toContain("Company applications");
    expect(html).toContain("Build data products.");
  });

  it("refreshes when command-center company discovery completes", async () => {
    const source = await readFile(new URL("./companies-list.tsx", import.meta.url), "utf-8");

    expect(source).toContain('window.addEventListener("jobops:companies-updated", loadCompanies)');
    expect(source).toContain('window.removeEventListener("jobops:companies-updated", loadCompanies)');
  });
});

function companyFixture(overrides: Partial<TrackedCompany> = {}): TrackedCompany {
  return {
    id: "company-1",
    company_id: "canonical-company-1",
    name: "Example Company",
    normalized_name: "example company",
    website_url: "https://example.com",
    careers_url: null,
    job_listings_url: null,
    description: "Example description.",
    headquarters_city: null,
    headquarters_country: null,
    operating_countries: [],
    hiring_locations: [],
    remote_policy: "unknown",
    role_fit_tags: [],
    mission_fit_tags: [],
    fit_reason: null,
    source_urls: [],
    source_summary: null,
    discovery_query: null,
    search_queries_used: [],
    discovered_by: null,
    derivation_status: "model_derived",
    review_status: "new",
    notes: "",
    created_at: "2026-05-18T12:00:00Z",
    updated_at: "2026-05-18T12:00:00Z",
    last_checked_at: null,
    ...overrides
  };
}
