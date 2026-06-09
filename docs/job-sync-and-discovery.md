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

Each provider refresh has a `sync_key`. A completed `job_sync_runs` row within the last 24 hours is fresh for that key. Failed runs do not satisfy freshness. When a refresh is skipped because the key is already fresh, Job Sync records a `job_sync_runs` row with `status="skipped_fresh"` for diagnostics, but skipped rows do not make a key fresh on their own.

Examples:

- `greenhouse:board:<board-token>`
- `adzuna:broad:<provider-country>:<location-key>:<query-text>`

## Provider Identity

Job Sync identity is provider-scoped only. This phase does not implement cross-provider dedupe and does not merge records by company, title, location, salary, or description. The same real-world job may appear as multiple `job_listings` rows when different providers return separate identities. Greenhouse IDs are scoped by board token, so the same Greenhouse job post ID on two board tokens remains separate.

Provider identity rules:

- Greenhouse: `source_provider + ats_board_token + provider_job_id`.
- Adzuna: `source_provider + provider_job_id`.

If a provider record does not include the stable provider id expected for that provider, treat it as failed normalization. Do not use job URLs for identity.

## Provider Request Diagnostics

`job_sync_runs.criteria_json` stores exact non-secret request values needed for debugging. It must preserve query and location values without truncation.

Examples:

- Adzuna: provider country endpoint, API path, page, `what`, `where`, `what_exclude`, `results_per_page`, content type, and sync key.
- Greenhouse: board token, list API URL, `content=true`, retrieve-job URL template, per-job retrieve URL and params, `questions=true`, `pay_transparency=true`, detail request counts, and sync key.

Never store provider secrets in diagnostics: no app ids, app keys, cookies, auth headers, bearer tokens, or private profile dumps.

## Provider Behavior

Greenhouse board sync refreshes a board token through the public jobs API with `content=true`, then retrieves each job with `questions=true` and `pay_transparency=true`. Detail retrieval is best-effort per job: if one retrieve-job call fails, the board sync continues and the job still syncs from the list-job payload when it has enough fields to normalize.

Each returned job gets a `job_listing_sources` row tied to the board token and provider job id. The source metadata retains the full list-job payload, retrieve-job payload when available, and exact per-job retrieve request values. Successful detail payloads include application questions, location questions, compliance/demographic question objects, exposed job metadata, departments, offices, language, requisition/internal IDs, and pay ranges. Failed or guardrail-skipped detail retrieval stores a concise safe error or skip object in source metadata without stack traces, headers, cookies, or secrets.

Greenhouse run diagnostics include detail request counts: attempted, succeeded, failed, and skipped by guardrail.

Adzuna broad sync signatures include provider country, location, and query text. Adzuna country is carried per sync request, so later inventory refreshes can support US, GB, and other provider endpoints without a single global country assumption.

## Location Normalization

This branch adds a small provider-aware location foundation, not a geocoder. Raw provider locations are stored separately from normalized fields.

Supported seed cases:

- `Remote US` -> provider country `us`.
- `Remote UK` -> provider country `gb`.
- `Louisville, KY` -> provider country `us`, provider where `Louisville, Kentucky`.
- `London, UK` -> provider country `gb`, provider where `London`.

Unknown locations are preserved as raw/display values with low confidence for later enrichment.
