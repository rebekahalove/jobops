# Job Sync and Discovery

JobOps now separates provider/API inventory refresh work from candidate-facing job discovery.

## Job Sync

Job Sync is provider/API inventory refresh. It stores normalized provider inventory for later search, filtering, and matching, but this branch does not replace the current candidate-facing live discovery flow.

Job Sync uses three database tables:

- `job_listings`: global synced job inventory records.
- `job_listing_sources`: provider-specific identity, provenance, and request context for each synced listing.
- `job_sync_runs`: provider refresh attempts, counts, status, and request diagnostics.

Existing `job_postings`, `candidate_saved_jobs`, and `applications` remain in place in this branch so applied jobs and application relationships stay intact. `JobPosting` should be revisited in a later migration as the candidate-facing workflows move to synced inventory. `CandidateSavedJob` should also be revisited for an eventual rename such as `CandidateJob` or `CandidateJobListEntry`, but that is deferred to avoid disturbing applied-job links.

## Candidate-Facing Discovery

The current candidate-facing job discovery behavior still uses the existing live provider adapters under `services/api/jobops_api/job_discovery/providers/`. Greenhouse still fetches boards and locally filters by role query. Adzuna still performs live broad searches from the request query and location values.

Future branches can move candidate-facing discovery to DB-backed search over `job_listings`, then use live provider calls as a refresh path when sync data is stale or missing.

## 24-Hour Sync Policy

Each provider refresh has a `sync_key`. A completed `job_sync_runs` row within the last 24 hours is fresh for that key. Failed runs do not satisfy freshness.

Examples:

- `greenhouse:board:<board-token>`
- `adzuna:broad:<provider-country>:<location-key>:<query-text>`

## Provider Identity

Job Sync identity is provider-scoped only. This phase does not implement cross-provider dedupe and does not merge records by company, title, location, salary, or description. The same real-world job may appear as multiple `job_listings` rows when different providers return separate identities.

Provider identity rules:

- Greenhouse: `source_provider + ats_board_token + provider_job_id`.
- Adzuna: `source_provider + provider_job_id`.

If a provider record does not include the stable provider id expected for that provider, treat it as failed normalization. Do not use job URLs for identity.

## Provider Request Diagnostics

`job_sync_runs.criteria_json` stores exact non-secret request values needed for debugging. It must preserve query and location values without truncation.

Examples:

- Adzuna: provider country endpoint, API path, page, `what`, `where`, `what_exclude`, `results_per_page`, content type, and sync key.
- Greenhouse: board token, API URL, `content=true`, and sync key.

Never store provider secrets in diagnostics: no app ids, app keys, cookies, auth headers, bearer tokens, or private profile dumps.

## Provider Behavior

Greenhouse board sync refreshes a board token through the public jobs API with `content=true`. Each returned job gets a `job_listing_sources` row tied to the board token and provider job id.

Adzuna broad sync signatures include provider country, location, and query text. Adzuna country is carried per sync request, so later inventory refreshes can support US, GB, and other provider endpoints without a single global country assumption.

## Location Normalization

This branch adds a small provider-aware location foundation, not a geocoder. Raw provider locations are stored separately from normalized fields.

Supported seed cases:

- `Remote US` -> provider country `us`.
- `Remote UK` -> provider country `gb`.
- `Louisville, KY` -> provider country `us`, provider where `Louisville, Kentucky`.
- `London, UK` -> provider country `gb`, provider where `London`.

Unknown locations are preserved as raw/display values with low confidence for later enrichment.
