# Alpha Auth And Tenant Isolation

Date: 2026-05-19

This is the MVP trusted-alpha authentication layer for onboarding a second JobOps user without exposing or modifying Rebekah's private data. It is not full SaaS auth.

## Data Model

Existing `tenants` are treated as workspaces. Auth tables:

- `users`: alpha user identity, including required unique URL-safe `username`.
- `workspace_memberships`: user-to-workspace ownership.
- `invite_tokens`: single-use alpha invite records; raw tokens are shown once and stored only as SHA-256 hashes.
- `user_sessions`: opaque server-side sessions keyed by an HttpOnly `jobops_session` cookie.
- `command_interaction_logs`: command-center audit/debug rows scoped by `user_id`, `tenant_id`, and `candidate_profile_id`.

`user.username` is the stable public/login identifier. `users.password_hash` stores a PBKDF2 password hash; raw passwords are never persisted. Display name is editable and must not change username or profile URLs automatically. Workspaces may keep their own slug, but the default alpha workspace/profile slug comes from username, not display name.

## Seed The Initial User

After migrations, seed the initial persisted user/workspace/profile:

```powershell
cd services/api
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m jobops_api.cli seed-initial-user --email rebekah@example.com --username rebekah-love --name "Rebekah Love" --password "<temporary-initial-password>" --require-reset
```

The command creates or repairs the user, workspace, owner membership, and primary candidate profile. Use a real temporary password locally, but do not commit it to docs, tests, or `.env` files. By default the command marks the seeded password expired and revokes existing sessions for that user, so first login routes to password reset. Use `--no-require-reset` only for local test fixtures where the seeded password should remain usable. If the public Rebekah profile was already seeded with slug `rebekah-love`, the command attaches the user/workspace shell to that existing profile instead of duplicating it.

## Username And Password Login

The JobOps login form asks for username and password. Next.js calls `POST /v1/auth/session` with only the submitted username/password. FastAPI verifies the DB-backed password hash, resolves the existing persisted user and that user's single alpha workspace, creates a `user_sessions` row, and sets the HttpOnly `jobops_session` cookie.

Unknown usernames or invalid passwords return a clear error and do not create users implicitly. Expired/reset-required passwords return a reset-required response; the frontend routes the user to `/reset-password`.

## Create An Invite

```powershell
cd services/api
.\.venv\Scripts\python.exe -m jobops_api.cli create-alpha-invite --email chance@example.com
```

The command creates a hashed invite token record for local/admin repair workflows. Use the admin dashboard or admin API for email invites.

```text
https://<jobops-host>/jobops/invite/<token>
```

For the standalone JobOps app, use `/invite/<token>`.

## Onboard A Second Alpha User

1. User opens `/jobops/invite/:token`.
2. Next.js posts the token to `/jobops/api/invites/accept`.
3. The invite page prompts for display name, username, and password.
4. FastAPI validates the hashed token, checks expiration and single-use state, creates or activates the user with the chosen username and hashed password, creates the workspace, membership, candidate profile, and server-side session.
5. FastAPI sets an HttpOnly `jobops_session` cookie with `SameSite=Lax`; production cookies are `Secure`.
6. The frontend routes the user into their own command center.

## Session Enforcement And Logout

The UI middleware only gates protected dashboard pages on the presence of the `jobops_session` cookie so it can quickly route anonymous browser traffic to login. Backend API routes enforce actual session validity through FastAPI, the internal API key, and the DB-backed `user_sessions` row.

Dashboard logout calls `POST /v1/auth/logout` with the current session cookie and internal API key, revoking the backend `UserSession`. The Next.js route clears the browser cookie regardless of backend success so the user is never stuck with a stale local cookie.

## Invite Email Configuration

Required public app URL for account email links:

```text
JOBOPS_APP_BASE_URL=https://<jobops-host>
```

Optional SMTP settings:

```text
JOBOPS_SMTP_HOST=smtp.example.com
JOBOPS_SMTP_PORT=587
JOBOPS_SMTP_USERNAME=...
RESEND_API_KEY=...
JOBOPS_SMTP_FROM_EMAIL=JobOps <no-reply@example.com>
```

If SMTP is not configured, invite creation still builds the configured public URL and returns `emailSent=false` for local/manual testing.

## Reset A Test Workspace

```powershell
cd services/api
.\.venv\Scripts\python.exe -m jobops_api.cli reset-test-workspace --workspace-slug chance-alpha
```

This removes mutable application/company/job/session/command-log data for the workspace while keeping the user/workspace/profile shell.

## Inspect Workspace State

```powershell
cd services/api
.\.venv\Scripts\python.exe -m jobops_api.cli inspect-alpha-workspaces
```

Authenticated protected endpoint:

```text
GET /v1/auth/debug/workspaces
```

## Tenant Scoping Rules

- Private API routes require both the internal API key and `jobops_session`.
- Login and private authorization come from the authenticated session/workspace, not from username values in URLs or request bodies.
- Client-supplied `candidate_profile_id`, `candidate_profile_slug`, `workspace_id`, `tenant_id`, `user_id`, and slug values are ignored for private workspace selection.
- Reads for companies/applications/profile draft/command center use the authenticated workspace profile.
- Record mutations verify ownership by `candidate_profile_id`; cross-workspace IDs return 404.
- Model/router context is built only from the authenticated candidate profile's companies, profile draft, and target context.
- Model-suggested actions are treated as untrusted suggestions. The backend validates type, fields, target records, and workspace ownership before applying.

## Command Logging

Each command-center request logs timestamp, user/workspace/profile IDs, user message, selected route, model provider, parsed action payload, validation result, applied status, final response, error details, and latency.

## Alpha Privacy And Cookies

`/privacy` documents the alpha privacy posture:

- JobOps uses essential HttpOnly session cookies for authentication.
- Alpha usage may store profile, company, job, application, command-center interaction, action/log, debugging, and error data.
- Alpha users should not enter highly sensitive information.
- This branch does not introduce analytics, advertising, session replay, or non-essential cookies.
- Before beta/public launch, add a full privacy policy, terms, cookie notice/preferences if analytics or non-essential cookies are introduced, and export/delete data processes.

## Red-Team Harness

Run:

```powershell
cd services/api
.\.venv\Scripts\python.exe -m pytest tests\test_alpha_auth_tenant_isolation.py
```

Covered scenarios:

- unauthenticated command-center access is rejected
- invite token creation/acceptance/session/current-user flow
- username validation, uniqueness, and unknown-username login rejection
- initial user seed creates user/workspace/membership/profile
- alpha user cannot list or update Rebekah applications
- client-supplied Rebekah profile IDs are ignored on writes
- "show me Rebekah's data" does not leak Rebekah company/application context
- model-proposed cross-tenant company IDs are rejected as missing/ambiguous
- safe company URL updates remain allowed inside the authenticated workspace

## Migration Note

This branch uses a follow-up migration, `20260519_0007_username_identity.py`, because the earlier alpha-auth migration had already been applied in the local dev database. The follow-up migration adds/backfills `users.username` and `invite_tokens.username`, then enforces non-null users plus a unique username index.

## Remaining Risks And Follow-Ups

- Add passwordless login or email magic links before wider alpha.
- Add explicit destructive-action confirmation state.
- Add workspace switcher only after multi-workspace users exist.
- Add better session revocation/audit UI.
- Move invite creation behind a stronger admin mechanism before public exposure.
- Add full privacy policy, terms, and export/delete flows before beta/public launch.
