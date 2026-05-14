# AI Command Center Shell

JobOps is moving from separate workflow pages toward one AI-first command center with structured workspace tabs beneath it.

The product model is:

1. The user talks to one prominent JobOps agent.
2. The agent plans or executes actions across the private job-search workspace.
3. Tabs keep the underlying workspaces inspectable and editable.

The shell currently supports these workspace tabs:

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

## Planned Agent Actions

The current UI uses local TypeScript action plans only. Supported action types are:

- `add_job_from_url` -> Jobs
- `follow_company` -> Companies
- `prioritize_jobs` -> Jobs
- `generate_materials` -> Materials
- `mark_applied` -> Applications
- `update_profile` -> Profile
- `follow_up_review` -> Follow-ups
- `unknown` -> command center review

Each planned action includes an id, type, title, summary, status, target workspace when known, and optional CTA label.

## Backend Ownership Boundary

Do not call models directly from Next.js.

TODO: real command handling should go through FastAPI. FastAPI will own agent command routing, tool execution, model calls, job URL intake, company follow, fit analysis, materials generation, and persistence. Next.js remains the UI and thin proxy layer.

For this branch, command handling is local and mocked:

- The UI echoes what JobOps understood.
- The UI classifies the command into a planned action type.
- The UI shows a planned action card.
- No job URL fetching, scraping, browser automation, or generated materials are performed.

## Deferred Features

- Real command execution.
- Job URL fetching and extraction.
- Company discovery and search.
- Job prioritization.
- Fit analysis.
- Generated materials.
- Browser automation.
- Auth.
