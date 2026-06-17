# Initial Data Model

This is a planning-level model for the Neon Postgres schema. Exact columns should be finalized during the first migration, but the core boundaries should be stable.

## Principles

- Domains are routing records, not identity.
- Tenants are the access boundary.
- Candidate profiles are publishable profile records within a tenant.
- Profile facts are verified claims with source metadata.
- Private JobOps data is never committed to the repo.
- Once a data type has CRUD, it belongs in Postgres and is managed by Alembic.

## Core Tables

`tenants`

- Workspace/account boundary.
- First tenant: Rebekah Love.
- Future tenants: invited candidates or candidate teams.

`users`

- People who can sign in through alpha username/password auth.
- Sessions are server-owned and tenant-scoped; OAuth, teams/RBAC, and account recovery remain deferred product work.

`candidate_profiles`

- Candidate identity and public profile publication state.
- Belongs to a tenant.
- Has a stable slug independent of hostname.

`profile_facts`

- Verified candidate claims.
- Belongs to a candidate profile.
- Includes fact type, structured value, source label, visibility, verification status, and timestamps.
- Public agent responses can use only published, verified facts.

`skill_claims`

- Structured claims about skills, proficiency, years experience, recency, and evidence.
- Belongs to a candidate profile.
- Should link to profile facts and experiences rather than existing as unsupported tags.
- Years experience should be stored as a range or lower bound when exact precision would be misleading.

`role_targets`

- The candidate's target roles, seniority, domains, locations, work mode preferences, constraints, and positioning goals.
- Used to guide profile intake, role-fit analysis, and application packet generation.
- Current implementation still stores list-like target role values as JSON arrays in the table but exposes several fields as compact strings in the profile-intake model schema. Location strings should use semicolon separators when city/state commas are present, such as `Louisville, KY; London, UK`. A future schema pass should expose these fields as structured arrays end to end.

`resume_artifacts`

- Uploaded resumes or parsed resume records.
- Belongs to a candidate profile.
- Stores metadata, parsing status, and source reference.
- Resume-derived details become draft facts, not verified facts.

`profile_intake_sessions`

- Agent-assisted Q&A sessions for profile setup.
- Starts from target role intent and optional resume upload.
- Should store structured state and redacted events by default.
- The active intake prompt is hydrated from the database-loaded saved draft snapshot. Client-provided draft state is compatibility/debug context only and is not authoritative.
- The model returns a full `updatedDraftProfile`, and persistence synchronizes editable draft rows to that returned full draft while preserving status, visibility, publication, and published/approved metadata by item ID.
- When no active draft exists after publication, intake should create a new private, unpublished draft copy from published profile values before applying changes. The backend currently seeds published role targets and published profile facts into editable draft rows; full published-profile edit UX remains deferred.

`profile_fact_drafts`

- Candidate facts proposed by the intake agent.
- Requires human approval before becoming verified or public.
- Includes source, confidence, suggested visibility, and review status.

`evidence_artifacts`

- Links or documents supporting profile facts, such as GitHub repos, demos, certificates, writing, talks, or project artifacts.
- Visibility and access policy must be explicit.

`domains`

- Hostnames mapped to candidate profiles or dashboard surfaces.
- Includes hostname, purpose, verification status, canonical flag, and timestamps.
- Examples: `rebekahalove.dev`, `jobops.rebekahalove.dev`, future custom domains.

`companies`

- Global canonical company records shared across candidate profiles.
- Stores shared facts such as normalized name/domain, website, careers and job-listing URLs, description, headquarters, operating countries, source URLs, confidence, first seen, and last seen.
- Stores ATS/provider metadata that is company-level, such as Greenhouse board token, Ashby board URL, and Lever slug.
- Must not store user-specific notes, review status, or fit rationale.

`candidate_companies`

- Profile-specific links between a candidate profile and a canonical company.
- Stores private relationship state such as review status, derivation status, fit reason, role and mission fit tags, notes, discovery query, search queries, discovered-by provider, added date, archive date, and last checked date.
- Different profiles can follow the same canonical company with separate notes, statuses, and fit reasons.
- Company cards and the company detail page combine canonical company facts with this user-scoped link state. Provider-derived company facts, such as domain, website, careers URL, job-listings URL, Greenhouse token, Ashby board URL, Lever slug, headquarters, hiring locations, remote policy, source summary, and compact provider metadata, come from `companies` plus summarized `candidate_companies.provider_grounding_metadata`. User/internal metadata, such as review status, derivation status, discovered-by label, added date, archived date, confidence, and last checked date, stays visually secondary.

`job_roles`

- Roles discovered, saved, or manually entered by a tenant.
- May include source URL, company, title, location, level, and raw description storage policy.
- Implemented for manual entry with source URL, company link, title, location, source, and status. Raw descriptions remain deferred.

`applications`

- Application records tied to candidate profiles and roles.
- Tracks status, dates, next action, and human-approved materials.
- Implemented with company name, job title, job URL, location, source, date applied, status, notes, next follow-up date, and timestamps.
- Current statuses: `saved`, `applied`, `interviewing`, `rejected`, `offer`, `closed`, `withdrawn`.
- Company detail pages include applications for the authenticated profile when `applications.company_id` matches the canonical company or when the application links through `applications.saved_job_id -> candidate_saved_jobs.job_listing_id -> job_listings.company_id`.

`job_listings`

- Provider/API-backed job inventory refreshed by Job Sync.
- Stores normalized job facts used for DB-backed discovery, including provider URLs, title, company, location, work mode, compensation, description excerpt/full description, posting/source dates, active/closed state, and location target links.
- Does not create candidate saved-job rows by itself; candidate-facing selection happens separately.
- Company detail pages show jobs associated by `job_listings.company_id = companies.id` first. Rows without `company_id` can be shown by normalized company-name fallback only when the synced job has not been canonicalized to a company yet.

`job_listing_sources`

- Provider-scoped source records for a `job_listings` row.
- Stores provider identity, board/query metadata, exact raw provider payloads, raw location values, active/closed state, and sync timestamps.
- Greenhouse source rows also store normalized retrieve-job application data in `application_fields_json`, compact material-generation requirements in `application_requirements_json`, and pay range details in `pay_transparency_json`.
- These normalized application fields are derived from provider API payloads and are used as untrusted context for draft materials; raw payloads remain preserved for audit/debugging.

`application_events`

- Timeline of application state changes, follow-ups, interviews, and notes.
- Implemented with event type, event date, notes, and `metadata_json`.

`role_fit_analyses`

- Saved role-fit outputs.
- Stores structured analysis, model/prompt version, score, and references to profile facts used.

`usage_events`

- Tenant-scoped product and quality metrics.
- Should store metadata by default, not raw chat text or full job descriptions.

## Public Seed Data

Approved public profile seed data may live in:

```text
packages/profile/data/rebekah-love.public.seed.json
```

That seed data is allowed because it is intentionally public and useful for review, bootstrapping, and evals. Production profile facts should be stored in Postgres after seeding.

## Privacy Defaults

Do not store raw candidate-agent questions or pasted job descriptions by default.

If raw text storage is added later, it needs:

- Explicit purpose.
- Tenant isolation.
- Redaction rules.
- Retention policy.
- User-facing disclosure or consent where appropriate.
