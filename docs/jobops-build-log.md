# JobOps Build Log / Consultancy Notebook

## Project Goal
Build an AI-assisted career operations system that helps users maintain a structured profile, track target companies/jobs/applications, and use a command-center assistant to route natural-language requests into validated, auditable actions.

## Timeline

### 2026-05-07 — Project kickoff / initial MVP direction
- Purchased/used rebekahalove.dev as the portfolio/project home.
- Started JobOps as a portfolio-grade AI product for job-search operations.
- Initial scope: profile/portfolio, job-fit workflow, hosted demo, Codex-assisted build.

### 2026-05-08 to 2026-05-10 — Product framing and architecture direction
- Chose JobOps as the project direction/name.
- Clarified that the app should serve both my own job search and portfolio positioning.
- Began treating the project as an applied-AI workflow system, not just a tracker.

### 2026-05-11 to 2026-05-15 — Profile intake, backend/model connector, deployment
- Built/iterated profile intake and app shell.
- Added FastAPI backend and provider/model connector direction.
- Moved toward a central command-center assistant.
- Encountered and debugged profile-state persistence issues.
- Clarified that the model should receive current draft profile state and return modified structured state.

### 2026-05-18 to 2026-05-19 — Command center, routing, second-user planning
- Added or planned model command routing.
- Identified routing issue where URL-related commands were overclassified as “add job by URL.”
- Decided router needs compact current saved state for higher-confidence routing.
- Confirmed main demo slice is mostly ready.
- Decided next major workstream is safe second-user onboarding.


## Key Architecture Decisions

### Central command center
Decision: Use one primary AI command center instead of separate page-specific chat windows.
Reason: Makes the product feel like an agentic career operations system and lets tools/actions expand over time.

### Model-suggested actions, backend-owned validation
Decision: The model can suggest JSON-encoded actions, but the backend owns identity, authorization, validation, and persistence.
Reason: Safer, more auditable, and better aligned with applied-AI production patterns.

### Second-user onboarding before full metrics layer
Decision: Prioritize auth/workspace scoping before building a full metrics/self-improvement layer.
Reason: Multi-user boundaries force the architecture to become real; metrics are more meaningful once there is actual alpha-user behavior.

### Main-slice demo, not full SaaS product
Decision: Optimize for a working vertical slice within ~20 days, not complete SaaS readiness.
Reason: Tomoro-style expectations emphasize rapid, useful, demoable AI workflows.

## Challenges / Open Risks

- Avoiding hardcoded single-user assumptions.
- Ensuring model context is scoped to authenticated user/workspace.
- Preventing natural-language commands from touching another user’s data.
- Improving router accuracy as tools/actions expand.
- Capturing metrics and artifacts without overbuilding too early.
- Creating a clear whiteboard/architecture narrative.

## Stakeholder / User Validation

### 2026-05-19 — Alpha tester outreach
Reached out to Chance as a potential second user/alpha tester.

Positioning:
- Free alpha use in exchange for honest feedback.
- Current functionality: build profile/portfolio, search/follow companies based on targets.
- Coming functionality: relevant job discovery, tailored materials, application tracking, optional email-based status updates, correspondence/interview helper.

Feedback goals:
- What feels useful?
- What is confusing?
- What would a user trust the agent to change automatically?
- What should require review before saving?
- What workflows matter most to someone actively looking for work?

### 2026-05-19 - Second-user onboarding / alpha auth / tenant isolation
- Milestone: Second-user onboarding / alpha auth / tenant isolation.
- Decision: Prioritize safe multi-user workspace scoping before full metrics/self-improvement layer.
- Rationale: A second trusted user makes the app a real alpha product and creates a stronger portfolio/demo story.
- Risks: cross-tenant leakage, model action mis-scoping, overbuilding auth too early.
- Next: onboard first alpha tester and collect feedback.

### 2026-05-19 - Persisted username identity before alpha onboarding
- Milestone: Alpha auth refinement / username-based identity.
- Decision: Moved from ENV-backed default user to persisted username-based user identity before onboarding a second alpha user.
- Rationale: Login and public/profile URL identity should be stable database state, not local environment configuration.
- Risks: migration/backfill edge cases, username collisions, stale local sessions after changing login shape.
- Next: seed the initial Rebekah user, create the first alpha invite with a unique username, and validate the onboarding loop.
