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

- People who can sign in once auth is implemented.
- May be deferred in the first migration if auth is not yet being built, but the model should leave room for it.

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

`target_companies`

- Private companies a tenant is tracking.
- Not visible to public profile visitors.
- Implemented for the manual Application Tracker MVP as candidate-profile-scoped company records.

`job_roles`

- Roles discovered, saved, or manually entered by a tenant.
- May include source URL, company, title, location, level, and raw description storage policy.
- Implemented for manual entry with source URL, company link, title, location, source, and status. Raw descriptions remain deferred.

`applications`

- Application records tied to candidate profiles and roles.
- Tracks status, dates, next action, and human-approved materials.
- Implemented with company name, job title, job URL, location, source, date applied, status, notes, next follow-up date, and timestamps.
- Current statuses: `saved`, `applied`, `interviewing`, `rejected`, `offer`, `closed`, `withdrawn`.

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
