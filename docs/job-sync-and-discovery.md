# Job Sync and Discovery

JobOps separates provider/API inventory refresh work from candidate-facing job discovery.

## Job Sync

Job Sync is provider/API inventory refresh. It stores normalized provider inventory for later search, filtering, and matching. Candidate-facing discovery is DB-backed only: it searches this synced inventory or ingests explicit direct job URLs into the same synced listing model.

Job Sync uses four core database tables:

- `job_listings`: global synced job inventory records.
- `job_listing_sources`: provider-specific identity, provenance, and request context for each synced listing.
- `job_sync_signatures`: durable provider search/source definitions that should be refreshed on a cadence.
- `job_sync_runs`: provider refresh attempts, counts, status, and request diagnostics.

`job_sync_signatures` are desired sync sources. `job_sync_runs` are history. A broad provider search should be refreshed because a signature row says so, not because a broad term is hard-coded in source code, migrations, or seed data.

The legacy `job_postings` table and `job_id` saved-job/application links have been removed. Jobs-list rows now point at synced inventory through `candidate_saved_jobs.job_listing_id`, and applications link through `applications.saved_job_id` plus denormalized application fields. Data that only existed in the removed live-provider `job_postings` path is intentionally not preserved by this cleanup branch.

## Candidate-Facing Discovery

Candidate-facing job discovery keeps the existing chat/run shell and `job_search_runs`, but the internals now use DB-backed synced inventory:

- The model planner emits a structured JSON plan for both sync signatures/sync tokens and DB search queries, not SQL.
- The query builder translates the plan into SQLAlchemy queries over `job_listings`, `job_listing_sources`, and jobs-list state.
- The model chooses a discovery `mode`: `new_job_discovery`, `jobs_list_review`, `mixed_new_and_existing`, `direct_job_url`, or `clarification_needed`.
- The backend maps model-selected modes onto internal query scopes only after validating the model plan structure.
- For new discovery, the reviewer model chooses which synced jobs should be added to the jobs list and which should be recorded as model rejected.
- For jobs-list ranking, the reviewer model recommends the best existing jobs-list entries without adding or rejecting rows.
- Chat-facing summaries use the reviewer-provided `userVisibleSummary`.

Pre-revamp live-provider discovery is intentionally removed. Direct URL ingestion is DB-backed: supported direct job URLs write normalized inventory into `job_listings` and `job_listing_sources`, then create or refresh `candidate_saved_jobs.job_listing_id`.

## Company Workspace and Detail Page

The Companies workspace now has a company detail page for each profile-linked `CandidateCompany`. Company cards and detail headers separate provider-derived company facts, readable company description, user/internal metadata, and actions:

- Provider facts are shown prominently: website/domain, careers URL, job-listings URL, Greenhouse board token, Ashby board URL, Lever slug, headquarters, hiring locations, remote policy, source count, and compact provider metadata such as technologies or keywords when already stored.
- The company description is shown as a multi-line scrollable panel. It is not truncated to a one-line preview.
- User/internal metadata is secondary: added date, first/last seen, last checked, review status, derivation status, data confidence, discovered-by label, and archive state.
- External links render only for safe `http:` or `https:` URLs. Internal placeholders or malformed values are not shown as website/careers/job links.

The company detail page shows related synced jobs and applications without reintroducing legacy `JobPosting` behavior. Related jobs come from `job_listings.company_id = companies.id`, with a normalized-name fallback only for synced rows that lack `company_id`. Related applications are scoped to the authenticated candidate profile and come from `applications.company_id` or from the saved-job path `applications.saved_job_id -> candidate_saved_jobs.job_listing_id -> job_listings.company_id`.

Company list counts are calculated server-side for the current candidate profile:

- Active job count: active synced `job_listings` associated with the company.
- Saved job count: visible, unarchived `candidate_saved_jobs` for this profile linked to the company's synced listings.
- Application count: this profile's applications associated with the company directly or through saved synced jobs.
- Open application count: profile-scoped applications that are not archived and not terminal withdrawn/rejected rows.

Company pages do not automatically sync boards merely because a user views a company. A future explicit company-level sync action can call first-party Greenhouse/Ashby sync for that company's stored board metadata, but passive page rendering remains read-only in this branch.

## TheirStack Company Enrichment Foundation

TheirStack is a company/enrichment source, not the canonical job detail source. The TheirStack foundation can search companies explicitly through the provider service, normalize company metadata, infer supported ATS identifiers from returned job/career URLs, and persist companies through the existing canonical company path.

TheirStack model-planned company enrichment is available for company discovery/enrichment and hiring-signal leads. The command-center company discovery path can ask a dedicated planner whether to use TheirStack. TheirStack is called only when that model plan explicitly requests company enrichment; there is no backend keyword router that turns words like Greenhouse, AI, or marketing into provider calls.

TheirStack is not used for saved-jobs ranking, direct job URL ingestion, or verified job-detail retrieval. TheirStack-discovered company leads can optionally feed first-party Greenhouse or Ashby board sync when the model-planned enrichment request explicitly asks to act on those leads by finding jobs. First-party board sync after enrichment is required before JobOps can verify actual current company-board jobs.

When a company-enrichment plan sets `syncDiscoveredAtsBoards=true`, JobOps collects supported first-party ATS metadata from the companies linked by that enrichment run and calls the matching board sync providers. Supported post-enrichment board sync providers are currently Greenhouse and Ashby. Provider-specific flags such as `syncDiscoveredGreenhouseBoards=true` and `syncDiscoveredAshbyBoards=true` can narrow the sync when the user or model plan intentionally does so. Post-enrichment board sync uses only the explicit boards from that enrichment run; it does not include unrelated configured/global boards by default. When the same plan sets `searchSyncedJobsAfterBoardSync=true`, JobOps searches synced `job_listings` / `job_listing_sources` from those boards, asks the job reviewer model to select matching jobs, and saves selected rows to `candidate_saved_jobs.job_listing_id` only if `saveMatchingJobsToCandidateList=true` and `recommendOnly=false`.

Diagnostics for the company enrichment to board sync loop separate each stage:

- Company leads: `enrichedCompanyCount`, `linkedCompanyCount`, and ATS counts such as `greenhouseBoardTokenCount` and `ashbyBoardUrlCount`.
- Board sync: `boardsSelectedForSync`, `boardTokensSynced`, `ashbyBoardsSelectedForSync`, `ashbyBoardTokensSynced`, `boardSyncAttempted`, provider-specific completed/failed/skipped counts, total board sync counts, and raw/normalized/created/updated job counts.
- Synced-job search: `syncedJobPoolCount`, `jobsReviewedAfterBoardSyncCount`, `jobsAddedAfterBoardSyncCount`, `addedJobIds`, and `addedJobListingIds`.

Assistant copy must keep the source boundary clear: TheirStack found company hiring signals, Greenhouse or Ashby board sync fetched first-party jobs, and only those synced first-party jobs may be added or recommended as actual jobs.

Configuration uses:

- `JOBOPS_THEIRSTACK_API_KEY`
- `JOBOPS_THEIRSTACK_COMPANY_SEARCH_ENABLED`
- `JOBOPS_THEIRSTACK_COMPANY_SEARCH_LIMIT`
- `JOBOPS_THEIRSTACK_COMPANY_SEARCH_MAX_PAGES`
- `JOBOPS_THEIRSTACK_COMPANY_SEARCH_FRESHNESS_DAYS`

Company search defaults to enabled when `JOBOPS_THEIRSTACK_API_KEY` is present unless `JOBOPS_THEIRSTACK_COMPANY_SEARCH_ENABLED=false` is set. The default limit is 25 companies, default max pages is 1, and default freshness window is 30 days. TheirStack may consume credits per returned company, so diagnostics include a credit caution.

TheirStack URL inference reuses existing canonical company fields:

- Greenhouse board tokens are stored on `companies.greenhouse_board_token`.
- Ashby board URLs are stored on `companies.ashby_board_url`.
- Lever slugs are stored on `companies.lever_slug`.
- Workday, Workable, and unknown ATS URLs are preserved as unsupported/source URLs and are not treated as supported sync providers.

Useful enrichment-only metadata such as LinkedIn URL, industry, employee counts, funding fields, technology and keyword slugs, job counts, compact TheirStack payload metadata, and unsupported ATS URLs can be stored in `candidate_companies.provider_grounding_metadata` only when an explicit service call links the company to a candidate profile. Diagnostics are sanitized and never include API keys, bearer tokens, authorization headers, or raw huge payloads.

TheirStack response language must describe results as company leads or hiring signals, for example "TheirStack returned hiring signals" or "TheirStack indicates hiring activity." Do not describe these as verified JobOps job matches until a first-party board sync has fetched the company board directly.

Role, domain, geography, technology, and hiring-signal filters in TheirStack plans are derived from the latest user message, authenticated profile, candidate target context, saved-company context, or recent discovery context. They are not hardcoded to any role or field such as Applied AI, AI Engineer, LLM, software engineering, healthcare, product marketing, or Greenhouse.

## Company Sync

Company Sync parallels Job Sync for canonical company inventory. It uses bounded provider signatures, durable provider runs, freshness windows, canonical company rows, provider-source evidence, and DB-backed candidate discovery. It is not a global TheirStack mirror and it is not a TheirStack job-ingestion path.

Company Sync uses three core tables:

- `company_sync_signatures`: durable bounded company-source searches or enrichment targets.
- `company_sync_runs`: each refresh attempt, status, count, error, and sanitized diagnostics.
- `company_sources`: provider-specific canonical company evidence shared across users.

`company_sources` stores TheirStack company-source metadata such as provider company id, source URL, website/LinkedIn/careers URLs, ATS metadata, technology/keyword/funding/job-count signals, and last synced/seen timestamps. Candidate-specific fit, notes, and discovery context remain on `candidate_companies`.

Signatures are derived from demand and inventory gaps:

- Role/profile demand: the Company Sync Signature Planner receives `RoleTarget.target_titles`, role families, seniority, preferred locations, work modes, constraints, headline, relevant profile facts, recent request context, saved companies, saved jobs, and applications. The model proposes semantic TheirStack search criteria; the backend validates, clamps, dedupes, and persists the durable signature. Sync runs never re-plan these semantics.
- Aggregate demand: equivalent target/search segments across active profiles collapse to the same `sync_key` with capped, privacy-safe demand metadata.
- Job inventory: companies already represented by active/recent `job_listings` can produce enrichment signatures when canonical company metadata is weak or stale.
- Known user-linked companies: followed companies, companies attached to saved jobs, and application companies can produce enrichment signatures when domain, careers URL, ATS metadata, or provider evidence is missing.

Only semantic profile/target discovery uses the model planner. Identity enrichment from existing job listings, followed companies, saved jobs, and applications remains deterministic and uses company identity fields such as `company_domain_or`, `company_name_or`, or `company_name_partial_match_or`.

Planner guardrails:

- Unsupported TheirStack filters are removed.
- Limits and pages are clamped to bounded sync settings.
- Search terms are accepted when they appear directly in context or when the model supplies per-term grounding with an allowed grounding type, rationale, and `basedOn` references that exist in planner context.
- The backend validates references and safety boundaries, but it does not maintain a hard-coded semantic synonym map.
- Ungrounded optional filters are removed without forcing the whole signature into review when meaningful grounded criteria remain.
- `verification_status="needs_review"` is reserved for model-admitted uncertainty, unsupported or ambiguous main intent, unverifiable grounding, or no meaningful bounded criteria after validation.
- Empty broad searches are not persisted as runnable signatures unless broad discovery was explicitly requested.
- `needs_review` signatures are persisted disabled and are skipped by normal enabled sync runs.

The manual CLI entry point creates or updates a signature only; it does not call TheirStack:

```powershell
python -m jobops_api.cli upsert-theirstack-company-sync-signature --query "AI platform companies" --job-title-pattern "AI Engineer" --max-pages 1
python -m jobops_api.cli list-theirstack-company-sync-signatures --enabled-only
```

Signature derivation can inspect profile demand and inventory gaps:

```powershell
python -m jobops_api.cli derive-company-sync-signatures --candidate-slug rebekah-love
python -m jobops_api.cli derive-company-sync-signatures --from-job-listings --missing-company-metadata-only --active-jobs-only
python -m jobops_api.cli derive-company-sync-signatures --from-candidate-companies --from-saved-jobs --from-applications --candidate-slug rebekah-love
```

Run bounded refreshes with:

```powershell
python -m jobops_api.cli sync-theirstack-company-signatures --all-enabled
python -m jobops_api.cli sync-theirstack-company-signatures --signature-id <id> --force --max-pages 1
```

Company Sync defaults are intentionally slower than job sync. TheirStack company sync uses weekly-ish defaults unless overridden:

- `JOBOPS_THEIRSTACK_COMPANY_SYNC_FRESHNESS_HOURS`
- `JOBOPS_THEIRSTACK_COMPANY_SYNC_RESULTS_PER_PAGE`
- `JOBOPS_THEIRSTACK_COMPANY_SYNC_MAX_PAGES`
- `JOBOPS_THEIRSTACK_COMPANY_SYNC_MAX_SIGNATURES_PER_RUN`

Candidate-facing company discovery queries canonical `companies` plus active `company_sources` first. Only fresh source-backed matches short-circuit discovery and link selected companies into `candidate_companies` with `discovered_by="canonical_company_cache"` and provider/source metadata. Stale-only cache matches are diagnosed with `canonicalCacheMatchCount`, `freshCanonicalCacheMatchCount`, `staleCanonicalCacheMatchCount`, `cacheShortCircuited=false`, and a fallback reason, then discovery continues to the provider/model fallback path. Archived or avoided companies are not re-added.

Company sync diagnostics distinguish canonical company counts from provider-source counts:

- `canonicalCompanyUpsertedCount`, `canonicalCompanyCreatedCount`, and `canonicalCompanyUpdatedCount`.
- `companySourceCount`, `companySourceCreatedCount`, and `companySourceUpdatedCount`.
- `company_sync_runs.created_count` and `updated_count` represent canonical company row counts; source row counts live in `diagnostics_json`.

TheirStack Company Sync can discover ATS metadata that later feeds first-party Job Sync providers:

- Greenhouse board token -> Greenhouse board sync.
- Ashby board URL -> Ashby board sync.
- Lever slug -> stored as company evidence until a Lever job sync path exists.

Actual saved jobs still come from Job Sync providers and `job_listings` / `job_listing_sources`, not from TheirStack company search.

The planner never emits raw SQL. Provider refreshes remain behind Job Sync: Greenhouse and Ashby boards for followed companies can be refreshed before DB search only when the model plan asks for followed-company board sync, model-selected existing Adzuna signatures can be refreshed, and planner-proposed Adzuna signatures may be upserted/refreshed only when the plan supplies explicit search criteria. There are no hard-coded broad Adzuna terms in candidate discovery.

For requests such as `find jobs from my companies list`, `look for jobs at my saved companies`, `find new jobs from companies I'm following`, or `search my watched companies for jobs`, the correct DB-backed job-discovery plan is new-job discovery with `syncPlan.useFollowedCompanyBoards=true`. JobOps uses the candidate's non-archived `CandidateCompany` links, finds companies with Greenhouse or Ashby board metadata, syncs those first-party boards, searches the synced inventory, and saves/recommends selected jobs. If no followed companies have syncable board metadata, the response should say so and should not silently fall back to broad provider search unless the model plan explicitly asks for a broader search.

For `direct_job_url`, the planner must choose that mode because the user supplied a specific job URL to add/save. The backend may structurally extract HTTP URLs only after the model-selected plan mode is `direct_job_url`; it does not route direct URL ingestion by keyword matching. Direct URL plans do not run broad provider sync, DB search queries, model review, model rejection recording, or stale/closed marking.

Supported Greenhouse direct URL shapes:

- `https://job-boards.greenhouse.io/{board_token}/jobs/{job_id}`
- `https://boards.greenhouse.io/{board_token}/jobs/{job_id}`
- `https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}`

Board-only Greenhouse URLs are not enough for direct ingestion; the URL must include a specific job id. Direct Greenhouse ingestion fetches the public board list with `content=true`, fetches the retrieve-job endpoint with `questions=true` and `pay_transparency=true`, merges those payloads, and normalizes through the same Greenhouse Job Sync mapper used by full board sync. Application fields, application requirements, raw list/retrieve payloads, and pay transparency are preserved on `job_listing_sources`. Direct URL ingestion records `job_sync_runs.sync_kind="direct_url"` with a sync key such as `greenhouse:direct-url:{board_token}:{provider_job_id}` and diagnostics for parsed URL kind, list/detail fetch status, listing/source ids, saved-job id, company ids, and create/refresh flags.

Direct Greenhouse ingestion resolves or creates a canonical `Company` by Greenhouse board token, ensures a `CandidateCompany` link exists, and avoids downgrading richer company metadata with board-token fallback names. It does not use `JobPosting`, does not create `candidate_saved_jobs.job_id`, and does not call full Greenhouse board sync or mark jobs missing from the board as closed.

The backend does not deterministically route discovery mode or generate search criteria from chat text. If model planning fails, returns invalid JSON, omits the required `mode`, omits required DB queries, or fails model critique, discovery records a no-op planning result and does not run Job Sync, DB search, model review, or jobs-list writes. Those runs report `noJobsAddedReason="model_planning_failed"`.

For new discovery, model-planned sync signatures refresh inventory before the DB query runs. The planner can also select existing Adzuna signatures to refresh/reuse. Jobs-list ranking searches existing jobs-list entries only. A `rank_existing_jobs` review never runs sync, adds jobs, records model rejections, or treats recommendations as newly selected jobs. Planner diagnostics expose each sync token with signature id, `sync_key`, provider, query text, query kind, display location, provider country/where, page bounds, enabled/review status, action, associated sync-run status, and raw/normalized/created/updated counts when a run happened.

Jobs-list ranking uses `reviewPlan.task="rank_existing_jobs"`. The requested number, such as "first 5 jobs", belongs in `reviewPlan.requestedCount`; it is not the DB query limit. The DB query limit is only an input safety cap and should retrieve all eligible visible, unarchived, unapplied jobs-list entries up to that cap. If the model sets the query limit equal to the requested recommendation count while more jobs may be eligible, the backend expands the query limit to the ranking input cap and records that correction in diagnostics. Filters such as US remote, London, AI, salary, company, role, title, or work mode narrow the jobs-list ranking pool; they do not imply new discovery.

Every model plan goes through a model critique step before execution. The critic checks whether the proposed mode matches the latest user message and context, whether the plan is executable, whether new discovery includes an inventory strategy, and whether jobs-list review makes sense for the current jobs-list count. If the critic rejects a plan and supplies a corrected plan, the corrected plan is used. If the critic rejects the plan without a correction, the planner is asked to replan with the critique. If planning/critique attempts fail, no sync, database search, model review, or jobs-list writes occur.

After sync and DB search, DB-backed discovery inspects the job pool size for new discovery. If the pool is below the model-supplied `minJobPoolSize` or above `maxJobPoolSize`, the backend asks the model for one result-based replan using execution facts such as query counts and pool size. The backend does not invent revised criteria. Jobs-list ranking skips pool-size replanning because it should review the eligible saved-list entries rather than broaden into new inventory.

Mixed new-plus-existing ranking must be an explicit two-phase workflow: discover and add new jobs first, then reload eligible jobs-list entries and rank that refreshed list. The backend does not allow a one-pass flow where an `all_accessible_jobs` ranking result both adds jobs and presents them as ranked existing recommendations. If the model accidentally combines `mixed_new_and_existing` with `rank_existing_jobs`, safety guards force the review back to jobs-list ranking behavior or the critic rejects the plan before execution.

DB-backed discovery persists each executed database query in `job_search_query_runs` with `provider_name="database"`, query label, location summary, result counts, and error details when applicable. Recent DB query history is included in later planner context so the model can avoid repeating zero-result searches.

Model-rejected synced jobs are retained as jobs-list rows with `status="model_rejected"` and active `candidate_job_rejection_reasons`. They are hidden from the normal jobs list until reset. This keeps review history available without presenting rejected jobs as saved jobs.

Model rejection reasons can be reset with:

```powershell
python -m jobops_api.cli reset-model-rejected-jobs --candidate-slug rebekah-love
python -m jobops_api.cli reset-model-rejected-jobs --candidate-slug rebekah-love --reason location
```

Resetting all active rejection reasons for a model-rejected job moves that row to `status="model_rejection_reset"`. This keeps it hidden from the normal jobs list while making it eligible for future `new_to_candidate` model review. Resetting rejections does not make a job visible as a selected or saved job.

If model review does not complete, DB-backed discovery does not auto-add the first synced jobs as a fallback. The run diagnostics report the database pool counts and model review fallback reason, but selected and rejected counts remain zero.

Model-selected and model-rejected `jobListingId` values are validated against the bounded job pool actually sent for review. Unknown IDs are ignored, duplicate decisions are deduped, and if the same job is both selected and rejected, the selected decision wins and no active rejection reason is created for that job. In jobs-list ranking, `rejectedJobs` from the model are ignored and recorded only as diagnostics; non-recommended jobs remain unchanged.

### DB-Backed Discovery Status and Debugging

Syncing inventory and selecting jobs are separate steps. A completed `job_sync_runs` row means provider inventory was refreshed or skipped as fresh; it does not mean any `candidate_saved_jobs` row was added. Candidate-facing discovery reports the distinction in the chat result payload and in `/v1/job-search-runs/latest` or `/v1/job-search-runs/{id}`.

DB-backed result/status payloads include:

- `jobSyncCompletedCount` and `jobSyncFailedCount` for provider refresh attempts.
- `databaseQueryCount` and `databaseMatchedJobCount` for synced-inventory search.
- `jobsReviewedByModel`, `modelReviewCompleted`, and `modelReviewFailureReason`.
- `addedToCandidateJobsList`, `recordedModelRejections`, `addedJobs`, and `addedJobIds`.
- For jobs-list ranking: `recommendedJobs`, `recommendedJobIds`, `recommendedExistingJobCount`, `requestedRecommendationCount`, and `eligibleJobsListCount`.
- `noJobsAddedReason` when nothing was added.

`noJobsAddedReason` is one of:

- `no_db_matches`: the synced-inventory database query returned no jobs.
- `model_review_failed`: synced jobs existed, but model review did not complete.
- `model_selected_zero`: model review completed and selected no jobs.
- `review_validation_removed_all_selected_ids`: selected IDs were outside the reviewed pool and were discarded.
- `all_selected_jobs_already_on_list`: selected jobs were already represented on the jobs list.
- `direct_url_missing_url`: the model chose direct URL ingestion, but the latest message did not include an HTTP URL.
- `unsupported_direct_job_url`: the direct URL provider registry does not support the supplied URL yet.
- `direct_url_ingestion_failed`: the direct URL was supported, but provider fetch/normalization did not produce a saved job.
- `unknown`: diagnostics were insufficient to classify the outcome.

DB-backed diagnostics are stored on `job_search_runs.run_diagnostics_json` and exposed to the UI in three sections:

- Planner: model-planned sync tokens/signatures and model-planned DB queries with actual fields, not just counts.
- Job Sync: each `syncKey`, status, raw, normalized, created, and updated counts.
- Database queries: each query label and matched job count, plus the unique pool count.
- Model review: unique jobs in pool, jobs reviewed by model, jobs added to the jobs list or recommended existing jobs, recorded model rejections, top rejection reasons, and model-review failure/no-added details when present.
- Direct URL ingestion: URL-level provider, status, parsed Greenhouse board token/job id, list/detail fetch status, listing/source ids, saved-job id, company ids, create/refresh flags, and safe error details.

Jobs added by the latest completed DB-backed discovery run keep `candidate_saved_jobs.job_search_run_id` and are highlighted first in the Jobs workspace. The saved-job API includes `jobSearchRunId`, `highlighted`, `justAdded`, and `latestDiscoveryRunId` so the UI can preserve that highlight after refresh.

For jobs-list review requests such as `which jobs`, `what jobs`, `show me the jobs`, `which jobs should I apply to first`, or `what US remote jobs should I apply to today`, the model should plan `mode="jobs_list_review"` with `reviewPlan.task="rank_existing_jobs"` and an explicit DB query over visible, unarchived, unapplied jobs-list entries. Those requests do not create new Adzuna sync signatures, refresh followed-company boards, add jobs, or reject jobs. New discovery requires explicit find, search, discover, add, new, or more wording. If the jobs-list pool is larger than one model request, the reviewer shortlists each batch and then makes a final top-N recommendation from the combined shortlist. UI and diagnostics describe these as recommended existing jobs, not newly added jobs, and non-recommended jobs are not model-rejected.

When a filtered jobs-list ranking request has fewer matches than requested, the run recommends the available matching jobs-list entries, reports the smaller count in diagnostics, and asks whether to search for new jobs. It does not automatically broaden into provider sync or new-job discovery.

In user-facing text and diagnostics, use found jobs, job pool, reviewed jobs, selected jobs, model-rejected jobs, jobs list, and jobs list entries. Reserve `candidate profile`, `candidate_saved_jobs`, and `CandidateSavedJob` for the person/profile and database concepts.

## 24-Hour Sync Policy

Each provider refresh has a `sync_key`. A completed `job_sync_runs` row within the last 24 hours is fresh for that key. Failed runs do not satisfy freshness. When a refresh is skipped because the key is already fresh, Job Sync records a `job_sync_runs` row with `status="skipped_fresh"` for diagnostics, but skipped rows do not make a key fresh on their own.

Examples:

- `greenhouse:board:<board-token>`
- `ashby:board:<org-slug>`
- `adzuna:broad:<provider-country>:<location-key>:<query-text>`

## Provider Identity

Job Sync identity is provider-scoped only. This phase does not implement cross-provider dedupe and does not merge records by company, title, location, salary, or description. The same real-world job may appear as multiple `job_listings` rows when different providers return separate identities. Greenhouse IDs are scoped by board token, so the same Greenhouse job post ID on two board tokens remains separate.

Provider identity rules:

- Greenhouse: `source_provider + ats_board_token + provider_job_id`.
- Ashby: `source_provider + provider_job_id`; the stored provider job id includes the normalized Ashby org slug to avoid cross-board collisions.
- Adzuna: `source_provider + provider_job_id`.

If a provider record does not include the stable provider id expected for that provider, treat it as failed normalization. Do not use job URLs for identity.

## Provider Request Diagnostics

`job_sync_runs.criteria_json` stores exact non-secret request values needed for debugging. It must preserve query and location values without truncation.

Examples:

- Adzuna: provider country endpoint, API path, page, `what`, `where`, `what_exclude`, `results_per_page`, content type, and sync key.
- Greenhouse: board token, list API URL, `content=true`, retrieve-job URL template, per-job retrieve URL and params, `questions=true`, `pay_transparency=true`, detail request counts, and sync key.
- Ashby: org slug, canonical board URL, posting API URL, response validity, raw job count, provider-id count, and sync key.

Never store provider secrets in diagnostics: no app ids, app keys, cookies, auth headers, bearer tokens, or private profile dumps.

## Provider Behavior

Greenhouse board sync refreshes a board token through the public jobs API with `content=true`, then retrieves each job with `questions=true` and `pay_transparency=true`. Detail retrieval is best-effort per job: if one retrieve-job call fails, the board sync continues and the job still syncs from the list-job payload when it has enough fields to normalize.

Each returned job gets a `job_listing_sources` row tied to the board token and provider job id. The source metadata retains the full list-job payload, retrieve-job payload when available, and exact per-job retrieve request values. Successful detail payloads include application questions, location questions, compliance/demographic question objects, exposed job metadata, departments, offices, language, requisition/internal IDs, and pay ranges. Failed or guardrail-skipped detail retrieval stores a concise safe error or skip object in source metadata without stack traces, headers, cookies, or secrets.

When Greenhouse retrieve-job details are available, Job Sync also stores normalized application form data on `job_listing_sources.application_fields_json`, a compact material-generation summary on `application_requirements_json`, and normalized pay input ranges on `pay_transparency_json`. These fields preserve resume, cover-letter, URL, location, compliance, demographic, short-answer, and pay-transparency signals separately from the raw provider payload. If a later detail call is skipped or fails, refresh preserves the previously stored normalized application fields instead of blanking them.

Greenhouse full-board Job Sync can be run independently of candidate-facing discovery. Board targets can come from configured board tokens, configured company board mappings, or candidate company records with Greenhouse board metadata. Greenhouse sync does not role-filter jobs and does not create candidate saved-job rows.

Greenhouse run diagnostics include board token, list URL, `content=true`, raw list count, provider-id count, retrieve params, max-detail guardrail, detail request counts, stale-closure eligibility, and closed counts. After a successful valid list-jobs response, any previously active Greenhouse source for that board token whose job id is missing from the latest list response is marked inactive/closed. A valid empty `jobs: []` response can close old board jobs, but malformed list responses do not trigger stale/closed marking. The associated synced listing is closed when it has no other active sources. If a closed Greenhouse job reappears later, its source and listing are reactivated. No stale/closed marking runs when the list-jobs request fails.

Greenhouse sync records a failed `job_sync_runs` row for a board-level list failure or malformed list response and continues syncing later board targets in the same service call.

Ashby board sync refreshes a public Ashby board through the first-party posting API for a normalized `jobs.ashbyhq.com/{org}` board URL. Board targets can come from explicit board URLs, configured board URLs, or candidate company records with `companies.ashby_board_url`. Ashby sync stores normalized `job_listings` and `job_listing_sources` with `source_provider="ashby"`, `provider_type="ats_board"`, `ats_provider="ashby"`, and the normalized Ashby org slug in `ats_board_token`. Raw Ashby job payloads are preserved in `job_listing_sources.raw_metadata_json`.

Ashby application-form normalization is intentionally limited in this branch. If Ashby exposes application fields in the public payload, the raw provider payload is preserved for future normalization, but Greenhouse remains the provider with normalized `application_fields_json` and material-generation application requirements today.

Ashby run diagnostics include org slug, board URL, posting API URL, response validity, raw job count, provider-id count, normalized/created/updated counts, and safe error details. A malformed or unavailable Ashby board records a failed `job_sync_runs` row and does not silently look complete.

Manual Greenhouse Job Sync examples:

```powershell
python -m jobops_api.cli sync-greenhouse-job-boards --board-token anthropic --force
python -m jobops_api.cli sync-greenhouse-job-boards --candidate-slug rebekah-love
python -m jobops_api.cli sync-greenhouse-job-boards --all-configured
```

Configured Ashby board sync targets can be supplied with `JOBOPS_ASHBY_BOARD_URLS` as a comma-separated list of `https://jobs.ashbyhq.com/{org}` board URLs or org slugs. Candidate-facing followed-company discovery usually gets Ashby targets from `companies.ashby_board_url` instead.

## Adzuna Signature-Driven Broad Sync

Adzuna broad-provider Job Sync is signature-driven. A persisted `job_sync_signatures` row combines:

- `provider_name="adzuna"` and `provider_type="broad_search"`.
- User/model supplied query text.
- Resolved location target and provider location mapping ids.
- Adzuna `provider_country` and `provider_where`.
- Paging settings such as `results_per_page` and `max_pages`.
- Freshness settings and last refresh metadata.
- Safe request criteria for diagnostics.

No production broad terms are seeded or assumed. CLI calls can create signatures from explicit user-supplied terms, and DB-backed candidate discovery may create model-planned signatures only from explicit structured plan criteria.

Manual Adzuna signature examples:

```powershell
python -m jobops_api.cli upsert-adzuna-sync-signature --query "AI" --location "Remote UK" --query-kind broad_term --max-pages 2
python -m jobops_api.cli upsert-adzuna-sync-signature --query "Engineer" --location "Louisville, KY" --query-kind broad_term
python -m jobops_api.cli list-adzuna-sync-signatures --enabled-only
python -m jobops_api.cli sync-adzuna-job-signatures --all-enabled
python -m jobops_api.cli sync-adzuna-job-signatures --signature-id <id> --force --max-pages 1
```

`upsert-adzuna-sync-signature` creates or updates the durable signature only. It does not call Adzuna, so raw/normalized/created/updated counts remain unchanged until `sync-adzuna-job-signatures` runs. The upsert output prints a request preview, including API path, query, location, page count, and the exact follow-up sync command.

For known mappings such as Remote UK, `provider_country` is resolved from `job_provider_location_mappings`; users should not need to pass `--provider-country gb`.

Adzuna request diagnostics include exact non-secret values: provider country, API path, `what`, `where`, `what_exclude`, `results_per_page`, page, max pages, sync key, signature id, display location, normalized location key, mapping ids, confidence/status, provider-reported count/mean/total, requested pages, fetched pages, failed pages, skipped pages, page numbers fetched, page errors, and per-page returned counts. Diagnostics never include `app_id`, `app_key`, auth headers, cookies, or private profile payloads.

Adzuna paging is bounded by the signature or CLI/service override. `results_per_page` defaults to 50 and `max_pages` defaults to 1. Broad searches can report large totals; Job Sync records provider-reported totals for diagnostics but fetches only configured pages. If a later page fails after earlier pages succeeded, the run is recorded as `partial`, earlier-page records are still persisted, and diagnostics include `partialSync=true` plus the failed page details. If the first requested page fails before any results are fetched, the run is recorded as failed.

For `job_sync_signatures`, `last_attempted_at` and `last_status` describe the latest sync attempt. `last_completed_at` and the last count fields describe the latest successful completed refresh and are not reset by skipped or failed attempts.

Adzuna raw results must include provider `id`. Missing `id` fails normalization; redirect URLs are not used as fallback identity. Adzuna broad searches do not mark jobs closed merely because a job is absent from a later broad search response, because broad provider searches are not exhaustive enough for strict stale marking.

Adzuna country is carried per sync request, so inventory refreshes can support US, GB, and other provider endpoints without a global country assumption.

## Location Normalization

Job Sync uses data-backed location targets and provider mappings instead of hardcoded location cases. When a user target location or command location needs provider search values, Job Sync resolves or creates:

- `job_location_targets`: normalized user-facing location targets such as `remote-uk`, `louisville-ky`, or `manchester-uk`.
- `job_provider_location_mappings`: provider-specific request values such as Adzuna `provider_country` and `provider_where`.

Seeded starter mappings cover Remote US, Remote UK, Louisville KY, London UK, and Manchester UK. New locations are auto-created with low confidence and `needs_review` status. Unknown locations can produce an inferred provider mapping when an explicit sync country hint is supplied, and those requests surface confidence/review metadata in Adzuna criteria. Adzuna does not default unresolved locations to the US: provider country must come from the resolved location mapping or explicit sync criteria. If neither source can resolve a country, planning fails clearly instead of generating a `/jobs/us` request.

Adzuna sync requests carry provider country, provider where, display location, normalized location key, mapping id, confidence, and verification status. Exact provider request values remain in `criteria_json`.

Provider-returned job locations are also resolved into `job_location_targets`. Structured Adzuna `location.area` values populate city, region, and country with medium confidence; text-only provider locations, such as Greenhouse `location.name`, are stored as low-confidence targets until reviewed. Raw provider job location values remain on `job_listings.location_raw` and `job_listing_sources.raw_location`, and the full provider payload remains in source metadata.

Location mappings can be reviewed with CLI maintenance commands:

```powershell
python -m jobops_api.cli list-job-location-mappings --status needs_review
python -m jobops_api.cli update-job-location-mapping --mapping-id <id> --provider-country gb --provider-where Manchester --confidence high --verification-status verified
```

Raw provider job locations are still stored separately on synced listings and source records.

## Application Materials

Application materials generation uses synced `job_listings` for saved jobs. For Greenhouse-backed saved jobs, materials context includes the normalized application requirements summary and compact application-fields summary from `job_listing_sources`. If an application is not linked to a saved synced listing, materials context falls back only to denormalized application fields such as company, role, URL, notes, and source. The prompt treats provider fields as untrusted context, grounds checklist and short-answer drafts in the actual application questions, and does not invent form requirements when fields are unavailable. Saved-job API serialization exposes a compact application-requirements summary so the UI can tell whether a synced job has form details such as resume, cover-letter, URL, or short-answer fields.
