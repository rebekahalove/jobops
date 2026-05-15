# AI Command Center Shell

JobOps is moving from separate workflow pages toward one AI-first command center with structured workspace tabs beneath it.

The product model is:

1. The user talks to one prominent JobOps agent.
2. The agent plans or executes actions across the private job-search workspace.
3. Tabs keep the underlying workspaces inspectable and editable.

The shell supports these workspace tabs:

- Profile
- Companies
- Jobs
- Applications
- Materials
- Follow-ups

## Why This Direction

The earlier dashboard made Profile, Jobs, Materials, and Applications feel like separate CRUD surfaces. The intended JobOps experience is closer to an operating console: the command center is the primary control surface, while the tabs are places to review, correct, and continue structured work.

Example future commands:

- "Here's a job URL. Add it to my jobs list."
- "Follow this company."
- "Which jobs should I apply to today?"
- "Prioritize my saved jobs."
- "Generate application materials for this role."
- "Mark this job as applied."
- "Update my profile with this project."
- "What should I follow up on this week?"

## Command Execution Boundary

Next.js remains a UI and thin proxy layer. It posts command-center submissions to FastAPI through:

- `POST /api/command-center` in Next.js
- `POST /v1/command-center/commands` in FastAPI

FastAPI owns:

- Command interpretation.
- Tool routing.
- Profile intake execution.
- Model calls.
- Draft persistence.

The command center now has one real tool:

- `profile_intake` -> Profile

Profile intake reuses the existing FastAPI profile intake workflow, including the Python model connector, Pydantic output validation, artifacts, redacted intake events, and DB-backed draft persistence. The command response includes an assistant message, action card data, `target_workspace = profile`, and the saved profile draft snapshot.

## Action Types

Supported and planned action types are:

- `add_job_from_url` -> Jobs
- `follow_company` -> Companies
- `prioritize_jobs` -> Jobs
- `generate_materials` -> Materials
- `mark_applied` -> Applications
- `profile_intake` -> Profile
- `follow_up_review` -> Follow-ups
- `unknown` -> command center review

Each planned action includes an id, type, title, summary, status, target workspace when known, and optional CTA label.

For unavailable APIs and tests, the UI can still fall back to local TypeScript action planning:

- The UI echoes what JobOps understood locally.
- The UI classifies the command into a fallback action type.
- The UI shows a fallback action card.

The fallback does not call a model and does not persist data.

## Profile Workspace

The Profile tab is no longer a separate chat experience. It is a structured review surface for saved profile draft state:

- Target role intent.
- Draft facts and claims.
- Skills.
- Experience and projects.
- Evidence links.
- Clarifying questions.
- Latest profile intake status.

The Profile tab loads the latest saved draft through the thin Next.js proxy at `/api/profile-draft`, backed by FastAPI's `/v1/command-center/profile-draft/{slug}`.

## Deferred Features

- Job URL fetching and extraction.
- Company discovery and search.
- Job prioritization.
- Fit analysis.
- Generated materials.
- Browser automation.
- Auth.
