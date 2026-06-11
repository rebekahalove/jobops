# Job Sync and Discovery

JobOps separates provider/API inventory refresh work from candidate-facing job discovery.

## Job Sync

Job Sync is provider/API inventory refresh. It stores normalized provider inventory for later search, filtering, and matching. Candidate-facing discovery now searches this synced inventory instead of calling live provider search adapters directly.

Job Sync uses four core database tables:

- `job_listings`: global synced job inventory records.
- `job_listing_sources`: provider-specific identity, provenance, and request context for each synced listing.
- `job_sync_signatures`: durable provider search/source definitions that should be refreshed on a cadence.
- `job_sync_runs`: provider refresh attempts, counts, status, and request diagnostics.

`job_sync_signatures` are desired sync sources. `job_sync_runs` are history. A broad provider search should be refreshed because a signature row says so, not because a broad term is hard-coded in source code, migrations, or seed data.

Existing `job_postings`, `candidate_saved_jobs`, and `applications` remain in place so applied jobs and application relationships stay intact. `candidate_saved_jobs.job_id` continues to support older live-provider saved jobs and applications. DB-backed discovery writes `candidate_saved_jobs.job_listing_id` for synced inventory entries and preserves application links that still point at `job_postings`.

## Candidate-Facing Discovery

Candidate-facing job discovery keeps the existing chat/run shell and `job_search_runs`, but the internals now use DB-backed synced inventory:

- The planner emits a structured JSON search plan, not SQL.
- The query builder translates the plan into SQLAlchemy queries over `job_listings`, `job_listing_sources`, and candidate job-list state.
- Supported query scopes are `new_to_candidate`, `candidate_jobs_list`, and `all_accessible_jobs`.
- The reviewer model chooses which synced jobs should be added to the candidate job list and which should be recorded as model rejected.
- Chat-facing summaries use the reviewer-provided `userVisibleSummary`.

The planner never emits raw SQL. Provider refreshes remain behind Job Sync: Greenhouse boards for followed companies can be refreshed before DB search, enabled Adzuna signatures can be refreshed, and planner-proposed Adzuna signatures may be upserted/refreshed only when the plan supplies explicit search criteria. There are no hard-coded broad Adzuna terms in candidate discovery.

Deterministic scope inference treats phrases like `which jobs`, `what jobs`, and `show me the jobs` as requests for the existing candidate jobs list. Phrases like `jobs to apply to`, `find jobs to apply to`, and `give me some jobs` are new discovery unless the user explicitly references saved, listed, already-surfaced, or existing jobs. `all_accessible_jobs` is reserved for explicit combined requests such as `all jobs`, `existing and new jobs`, or `new and saved jobs`.

Model-rejected synced jobs are retained as candidate job-list rows with `status="model_rejected"` and active `candidate_job_rejection_reasons`. They are hidden from the normal candidate-facing job list until reset. This keeps review history available without presenting rejected jobs as saved jobs.

Model rejection reasons can be reset with:

```powershell
python -m jobops_api.cli reset-model-rejected-jobs --candidate-slug rebekah-love
python -m jobops_api.cli reset-model-rejected-jobs --candidate-slug rebekah-love --reason location
```

Resetting all active rejection reasons for a model-rejected job moves that row to `status="model_rejection_reset"`. This keeps it hidden from the normal jobs list while making it eligible for future `new_to_candidate` model review. Resetting rejections does not make a job visible as a selected or saved job.

If model review does not complete, DB-backed discovery does not auto-add the first synced jobs as a fallback. The run diagnostics report the database pool counts and model review fallback reason, but selected and rejected counts remain zero.

Model-selected and model-rejected `jobListingId` values are validated against the bounded job pool actually sent for review. Unknown IDs are ignored, duplicate decisions are deduped, and if the same job is both selected and rejected, the selected decision wins and no active rejection reason is created for that job.

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

Greenhouse full-board Job Sync can be run independently of candidate-facing discovery. Board targets can come from configured board tokens, configured company board mappings, or candidate company records with Greenhouse board metadata. Greenhouse sync does not role-filter jobs and does not create candidate saved-job rows.

Greenhouse run diagnostics include detail request counts: attempted, succeeded, failed, and skipped by guardrail. After a successful valid list-jobs response, any previously active Greenhouse source for that board token whose job id is missing from the latest list response is marked inactive/closed. A valid empty `jobs: []` response can close old board jobs, but malformed list responses do not trigger stale/closed marking. The associated synced listing is closed when it has no other active sources. If a closed Greenhouse job reappears later, its source and listing are reactivated. No stale/closed marking runs when the list-jobs request fails.

Greenhouse sync records a failed `job_sync_runs` row for a board-level list failure or malformed list response and continues syncing later board targets in the same service call.

Manual Greenhouse Job Sync examples:

```powershell
python -m jobops_api.cli sync-greenhouse-job-boards --board-token anthropic --force
python -m jobops_api.cli sync-greenhouse-job-boards --candidate-slug rebekah-love
python -m jobops_api.cli sync-greenhouse-job-boards --all-configured
```

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

Adzuna request diagnostics include exact non-secret values: provider country, API path, `what`, `where`, `what_exclude`, `results_per_page`, page, max pages, sync key, signature id, display location, normalized location key, mapping ids, confidence/status, provider-reported count/mean, and per-page returned counts. Diagnostics never include `app_id`, `app_key`, auth headers, cookies, or private profile payloads.

Adzuna paging is bounded by the signature or CLI/service override. `results_per_page` defaults to 50 and `max_pages` defaults to 1. Broad searches can report large totals; Job Sync records provider-reported totals for diagnostics but fetches only configured pages.

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

## Branch 5 TODO

Adzuna inventory depth is still bounded by signature paging settings. Branch 5 should improve Adzuna pagination and inventory-depth strategy so DB-backed candidate discovery can reason about when broad-provider inventory is shallow, stale, or under-sampled before asking the model to review a pool.
