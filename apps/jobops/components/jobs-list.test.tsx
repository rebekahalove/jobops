import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import JobsPage from "../app/jobs/page";
import { JobDiscoveryDiagnostics, JobsList, buildJobBucketCounts, jobBucket, sortJobsForBucket, type SavedJob } from "./jobs-list";
import type { JobSearchRunStatus } from "../lib/command-center-contract";
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
            full_description: "Full provider job description with responsibilities, outcomes, and qualifications.",
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
    expect(html).toContain('id="saved-job-saved-job-1"');
    expect(html).toContain("Example Civic");
    expect(html).toContain("Remote US");
    expect(html).toContain("Full-time");
    expect(html).toContain("$150,000-$180,000");
    expect(html).toContain("May 28, 2026");
    expect(html).toContain("05/20/2026");
    expect(html).toContain("URL check");
    expect(html).toContain("Verified");
    expect(html).toContain("Fetched page confirmed the job title and company.");
    expect(html).toContain("Job Description");
    expect(html).toContain("Full provider job description with responsibilities, outcomes, and qualifications.");
    expect(html).toContain("Fit Summary");
    expect(html).toContain("Matches applied AI and platform engineering goals.");
    expect(html).toContain("In process");
    expect(html).toContain("View application");
    expect(html).toContain("Archive");
    expect(html).toContain("View Posting");
    expect(html).not.toContain("Job posting");
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

  it("shows complete scrollable job description and fit summary without repeated preview text", () => {
    const longDescription = [
      "**Role overview**",
      "Build applied AI workflows for civic data products without UI-added truncation.",
      "- Own retrieval quality",
      "- Partner with product teams",
      "See https://jobs.example.test/details for more."
    ].join("\n");
    const fitSummary = "Strong fit because of `LLM` product work, platform depth, and deployment experience.";
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          jobFixture({
            id: "long-description",
            title: "Formatted Description Role",
            full_description: longDescription,
            description_excerpt: "This excerpt should not be used when full description exists.",
            fit_summary: fitSummary
          })
        ]}
      />
    );

    expect(html).toContain("job-scroll-text job-description");
    expect(html).toContain("<strong>Role overview</strong>");
    expect(html).toContain("<li>Own retrieval quality</li>");
    expect(html).toContain('href="https://jobs.example.test/details"');
    expect(html).toContain("<code>LLM</code>");
    expect(html).not.toContain("This excerpt should not be used");
    expect(html).not.toContain(" More");
    expect(html).not.toContain("Build applied AI workflows for civic data products without UI-added truncation...");
  });

  it("renders sanitized provider HTML for job descriptions when available", () => {
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          jobFixture({
            id: "html-description",
            title: "HTML Description Role",
            description_html:
              '<h2>About Hightouch</h2><p>Build <strong>agentic marketing</strong> systems.</p><ul><li>Own product development</li></ul><a href="https://jobs.example.test/details" rel="noopener noreferrer" target="_blank">Details</a>',
            full_description: "Flattened text should not render when HTML is available.",
            description_excerpt: "Excerpt should not render."
          })
        ]}
      />
    );

    expect(html).toContain("<h2>About Hightouch</h2>");
    expect(html).toContain("<strong>agentic marketing</strong>");
    expect(html).toContain("<li>Own product development</li>");
    expect(html).toContain('href="https://jobs.example.test/details"');
    expect(html).not.toContain("Flattened text should not render");
    expect(html).not.toContain("Excerpt should not render");
  });

  it("keeps job card layout split into metadata, scrollable content, and action rail", async () => {
    const source = await readFile(new URL("../app/globals.css", import.meta.url), "utf-8");

    expect(source).toContain("grid-template-areas:");
    expect(source).toContain("\"posted compensation\"");
    expect(source).toContain("\"location employment\"");
    expect(source).toContain("\"work .\"");
    expect(source).toContain(".job-description-panel .job-scroll-text");
    expect(source).toContain(".job-fit-panel .job-scroll-text");
    expect(source).toContain(".job-card-rail .company-links");
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
    expect(source).toContain('status: "started"');
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
    expect(html).not.toContain("Application archived: Rejected");
    expect(html).toContain("Rejected");
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

  it("renders a persistent job discovery diagnostics affordance before a latest run loads", () => {
    const html = renderToStaticMarkup(<JobDiscoveryDiagnostics />);

    expect(html).toContain("Discovery diagnostics");
    expect(html).toContain("No recent job discovery diagnostics yet.");
    expect(html).toContain("Details");
  });

  it("renders the latest job discovery diagnostics with model explanation and scoped replan wording", () => {
    const html = renderToStaticMarkup(<JobDiscoveryDiagnostics initialRun={jobSearchRunFixture()} />);

    expect(html).toContain("Discovery diagnostics");
    expect(html).toContain("Completed - 0 saved - 0 model selected - 12 reviewed jobs - 12 unique jobs - 28 provider matches");
    expect(html).toContain("Initial search plan");
    expect(html).toContain("Applied AI Engineer");
    expect(html).toContain("Provider search timeline");
    expect(html).toContain("Initial search");
    expect(html).toContain("adzuna - Broad search");
    expect(html).not.toContain("adzuna - Broad search - query");
    expect(html).toContain("Query");
    expect(html).toContain("AI Engineer");
    expect(html).toContain("Where");
    expect(html).toContain("Remote US");
    expect(html).toContain("Anthropic");
    expect(html).toContain("Greenhouse - ATS board - Anthropic");
    expect(html).toContain("Board token");
    expect(html).toContain("Replan 1");
    expect(html).toContain("Next query");
    expect(html).toContain("Broad search reported 0 total matches");
    expect(html).toContain("Broad search reported 0 total matches, while company board searches returned candidates.");
    expect(html).toContain("Model review");
    expect(html).toContain("Model explanation");
    expect(html).toContain("I found roles from followed-company boards, but none matched strongly enough to save.");
  });

  it("renders DB-backed discovery diagnostics in Job Sync, database, and model sections", () => {
    const html = renderToStaticMarkup(
      <JobDiscoveryDiagnostics
        initialRun={jobSearchRunFixture({
          searchMode: "db_backed",
          jobDiscoveryMode: "db_backed",
          providerResultCount: 50,
          candidatePoolCount: 87,
          candidateCountAfterDedupe: 87,
          noJobsAddedReason: "model_selected_zero",
          diagnostics: {
            planner: {
              status: "planned",
              modelUsed: true,
              planningFailed: false,
              plannedSyncSignatures: [
                {
                  id: "sig-1",
                  syncKey: "adzuna:broad:gb:remote-uk:ai",
                  providerName: "adzuna",
                  queryText: "AI",
                  queryKind: "model_planned",
                  displayLocation: "Remote UK",
                  providerCountry: "gb",
                  providerWhere: null,
                  maxPages: 1,
                  resultsPerPage: 50,
                  enabled: true,
                  verificationStatus: "verified",
                  action: "created",
                  syncRunStatus: "completed"
                }
              ],
              plannedDbQueries: [
                {
                  label: "Model-planned AI/software search",
                  titleTermsAny: ["AI", "Engineer"],
                  descriptionTermsAny: ["LLM", "RAG"],
                  locationCountriesAny: ["GB"],
                  remoteWorkModesAny: ["remote"],
                  limit: 300
                }
              ]
            },
            jobSync: {
              runs: [
                {
                  syncKey: "adzuna:broad:gb:remote-uk:ai",
                  status: "completed",
                  raw: 50,
                  normalized: 49,
                  created: 12,
                  updated: 37
                }
              ]
            },
            databaseQueries: {
              queries: [{ label: "Broad AI/LLM search", jobCount: 87 }],
              uniqueJobPoolCount: 87
            },
            modelReview: {
              uniqueJobsInPool: 87,
              jobsReviewedByModel: 80,
              addedToCandidateJobsList: 0,
              recordedModelRejections: 80,
              modelReviewCompleted: true,
              topRejectionReasonCounts: { role_title: 12 }
            },
            noJobsAddedReason: "model_selected_zero"
          }
        })}
      />
    );

    expect(html).toContain("Job Sync");
    expect(html).toContain("Planner");
    expect(html).toContain("adzuna:broad:gb:remote-uk:ai");
    expect(html).toContain("Model-planned AI/software search");
    expect(html).toContain("AI, Engineer");
    expect(html).toContain("Database queries");
    expect(html).toContain("Broad AI/LLM search");
    expect(html).toContain("Model review");
    expect(html).toContain("Jobs reviewed by model");
    expect(html).toContain("No jobs added: Model review selected zero jobs");
    expect(html).toContain("Top rejection reasons: Role title: 12");
  });

  it("renders jobs-list ranking diagnostics as recommended existing jobs", () => {
    const html = renderToStaticMarkup(
      <JobDiscoveryDiagnostics
        initialRun={jobSearchRunFixture({
          searchMode: "db_backed",
          jobDiscoveryMode: "db_backed",
          savedCount: 0,
          modelSelectedCount: 0,
          message: "Only 3 matching saved-list jobs were available. Would you like me to search for new jobs?",
          userVisibleSummary: "Only 3 matching saved-list jobs were available. Would you like me to search for new jobs?",
          diagnostics: {
            planner: {
              status: "planned",
              mode: "jobs_list_review",
              reviewTask: "rank_existing_jobs",
              requestedRecommendationCount: 5,
              plannedSyncSignatures: [],
              existingSyncSignaturesSelected: [],
              plannedDbQueries: [
                {
                  label: "Review active unapplied US remote jobs from the jobs list",
                  locationCountriesAny: ["US"],
                  remoteWorkModesAny: ["remote"],
                  limit: 300
                }
              ]
            },
            jobSync: { runs: [] },
            databaseQueries: {
              queries: [{ label: "Review active unapplied US remote jobs from the jobs list", jobCount: 3 }],
              uniqueJobPoolCount: 3
            },
            modelReview: {
              uniqueJobsInPool: 3,
              eligibleJobsListCount: 3,
              jobsReviewedByModel: 3,
              requestedRecommendationCount: 5,
              selectedJobsLabel: "Recommended existing jobs",
              recommendedExistingJobCount: 3,
              addedToCandidateJobsList: 0,
              recordedModelRejections: 0,
              modelReviewCompleted: true,
              fewerThanRequestedRecommendations: true,
              availableMatchingSavedListJobs: 3
            }
          }
        })}
      />
    );

    expect(html).toContain("Review task: Rank existing jobs - recommend 5 existing jobs");
    expect(html).toContain("Review active unapplied US remote jobs from the jobs list");
    expect(html).toContain("Eligible jobs from list");
    expect(html).toContain("Recommended existing jobs");
    expect(html).toContain("Model rejections");
    expect(html).toContain("Only 3 matching saved-list jobs were available. Ask whether to search for new jobs.");
    expect(html).not.toContain("Just added to your jobs list");
  });

  it("renders favorite and unfavorite actions for active unapplied jobs", () => {
    const newHtml = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          jobFixture({ id: "job-new", status: "new", title: "New Role" })
        ]}
      />
    );
    const favoriteHtml = renderToStaticMarkup(
      <JobsList initialJobs={[jobFixture({ id: "job-favorite", status: "saved", title: "Favorite Role" })]} />
    );

    expect(newHtml).toContain("Favorite");
    expect(favoriteHtml).toContain("Unfavorite");
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

  it("sorts and highlights jobs from the latest discovery run first", () => {
    const jobs = [
      jobFixture({ id: "older", added_at: "2026-05-12T00:00:00Z" }),
      jobFixture({ id: "just-added", added_at: "2026-05-10T00:00:00Z", highlighted: true, justAdded: true })
    ];
    const html = renderToStaticMarkup(<JobsList initialJobs={jobs} />);

    expect(sortJobsForBucket(jobs, "new").map((job) => job.id)).toEqual(["just-added", "older"]);
    expect(html).toContain("job-card-just-added");
    expect(html).toContain("Just added");
  });

  it("does not badge recommended existing jobs as just added", () => {
    const jobs = [
      jobFixture({ id: "recommended-existing", highlighted: true, justAdded: false, title: "Recommended Existing Role" })
    ];
    const html = renderToStaticMarkup(<JobsList initialJobs={jobs} />);

    expect(html).toContain("Recommended Existing Role");
    expect(html).not.toContain("job-card-just-added");
    expect(html).not.toContain("Just added");
  });

  it("badges newly posted jobs by posting date, not saved date", () => {
    const recentPostingDate = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          jobFixture({
            id: "recent-posting",
            added_at: "2026-05-01T00:00:00Z",
            posting_date: recentPostingDate,
            title: "Recently Posted Role"
          })
        ]}
      />
    );

    expect(html).toContain("Recently Posted Role");
    expect(html).toContain("New");
    expect(html).not.toContain("Just added");
  });

  it("renders provider as source and provenance as how the job entered the list", () => {
    const html = renderToStaticMarkup(
      <JobsList
        initialJobs={[
          jobFixture({
            id: "synced-provider",
            source: "greenhouse",
            source_provider: "greenhouse",
            provenance: "job_sync",
            title: "Provider Labeled Role"
          })
        ]}
      />
    );

    expect(html).toContain("Provider Labeled Role");
    expect(html).toContain("Source");
    expect(html).toContain("Greenhouse");
    expect(html).toContain("Provenance");
    expect(html).toContain("Job sync");
  });
});

function jobSearchRunFixture(overrides: Partial<JobSearchRunStatus> = {}): JobSearchRunStatus {
  return {
    id: "run-1",
    status: "completed",
    searchMode: "followed_companies",
    providerResultCount: 28,
    candidatePoolCount: 12,
    candidateCountAfterDedupe: 12,
    modelSelectedCount: 0,
    savedCount: 0,
    updatedExistingCount: 0,
    duplicateCount: 16,
    skippedCount: 21,
    providerErrorCount: 0,
    startedAt: "2026-06-06T12:00:00Z",
    completedAt: "2026-06-06T12:02:00Z",
    error: null,
    message: "I found roles from followed-company boards, but none matched strongly enough to save.",
    userVisibleSummary: "I found roles from followed-company boards, but none matched strongly enough to save.",
    replansAttempted: 1,
    replanLimit: 1,
    replanningStatus: "attempted",
    replanningDecision: "triggered:zero_total_matches",
    replanReason: "zero_total_matches",
    replanReasons: ["zero_total_matches"],
    replanQueries: ["Applied AI Engineer"],
    diagnostics: {
      searchCriteria: {
        searchMode: "followed_companies",
        roleQueries: ["Applied AI Engineer"],
        companyNames: ["Anthropic"],
        locations: ["Remote US"],
        remoteWorkModes: ["remote"],
        salaryMin: 150000,
        excludeTerms: ["management"],
        maxProviderPages: 2
      },
      providerDiagnostics: [
        {
          providerName: "adzuna",
          providerType: "broad_search",
          attempted: true,
          configured: true,
          queryPreview: "AI Engineer",
          requestCriteria: {
            what: "AI Engineer",
            where: "Remote US",
            whatExclude: "manager",
            country: "us",
            page: 1,
            resultsPerPage: 17
          },
          rawResultCount: 0,
          resultCount: 0,
          normalizedResultCount: 0,
          totalMatches: 0,
          page: 1
        },
        {
          providerName: "Greenhouse",
          providerType: "ats_board",
          companyName: "Anthropic",
          boardToken: "anthropic",
          attempted: true,
          configured: true,
          queryPreview: "AI Engineer",
          rawResultCount: 0,
          resultCount: 0,
          normalizedResultCount: 0
        },
        {
          providerName: "adzuna",
          providerType: "broad_search",
          attempted: true,
          configured: true,
          queryPreview: "Applied AI Engineer",
          requestCriteria: {
            what: "Applied AI Engineer",
            where: "Remote US",
            whatExclude: "manager",
            country: "us",
            page: 1,
            resultsPerPage: 17
          },
          rawResultCount: 0,
          resultCount: 0,
          normalizedResultCount: 0,
          totalMatches: 0,
          page: 1
        },
        {
          providerName: "Greenhouse",
          providerType: "ats_board",
          companyName: "Anthropic",
          boardToken: "anthropic",
          attempted: true,
          configured: true,
          queryPreview: "Applied AI Engineer",
          rawResultCount: 28,
          resultCount: 28,
          normalizedResultCount: 28
        }
      ],
      replanning: {
        replansAttempted: 1,
        replanLimit: 1,
        replanReasons: ["zero_total_matches"],
        replanningDecision: "triggered:zero_total_matches",
        replanQueries: ["Applied AI Engineer"],
        displayLabel: "Broad search reported 0 total matches",
        displayMessage: "Broad search reported 0 total matches, while company board searches returned candidates.",
        triggerProviderName: "adzuna",
        triggerProviderType: "broad_search",
        companyBoardsReturnedCandidates: true,
        providerResultsExisted: true,
        candidatePoolExisted: true
      },
      modelReview: {
        candidateCountAfterDedupe: 12,
        candidatePoolCount: 12,
        modelSelectedCount: 0,
        savedCount: 0,
        updatedExistingCount: 0,
        duplicateCount: 16,
        skippedCount: 21,
        providerErrorCount: 0
      },
      modelExplanation: {
        userVisibleSummary: "I found roles from followed-company boards, but none matched strongly enough to save.",
        userSummary: "I found roles from followed-company boards, but none matched strongly enough to save.",
        plannerRationale: "Search followed company boards and broad providers for applied AI roles.",
        selectionAssistantMessage: "I found roles from followed-company boards, but none matched strongly enough to save.",
        skippedCandidateNotes: [{ candidateId: "CAND-1", reason: "Management-heavy role." }]
      }
    },
    ...overrides
  };
}

function jobFixture(overrides: Partial<SavedJob> = {}): SavedJob {
  return {
    id: "saved-job-1",
    candidate_profile_id: "profile-1",
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
