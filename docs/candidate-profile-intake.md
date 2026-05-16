# Candidate Profile Intake

This document defines the initial data categories and Q&A workflow for candidate profile setup.

The goal is not to make candidates fill out a giant form. The goal is to let a candidate upload a resume optionally, then talk with an intake agent that extracts draft profile facts, asks targeted follow-up questions, and prepares stronger verified profile data for target roles.

## Survey Snapshot

Reviewed on May 8, 2026.

Applied AI, AI Engineer, and Forward Deployed AI roles repeatedly emphasize:

- Shipped LLM, ML, or agentic products.
- Production Python and backend/data systems.
- Evals, regression testing, safety, and reliability.
- RAG, retrieval, tool use, context construction, and orchestration.
- Latency, cost, monitoring, observability, and production failure analysis.
- Product sense and measurable business/user outcomes.
- Customer-facing or cross-functional technical communication for FDE and applied AI roles.
- Domain-specific depth in areas such as education, finance, healthcare, security, coding agents, or enterprise workflows.

Application systems also repeatedly collect basic fields:

- Resume or CV.
- Name.
- Email.
- Phone.
- Location.
- Current company.
- Links such as LinkedIn, GitHub, portfolio, website, writing, or public code.
- Work authorization, sponsorship, relocation, start date, and timeline considerations for some employers.
- Voluntary demographic/EEO fields in some ATS workflows.

Sources:

- OpenAI, Applied AI Engineer, Codex Core Agent: https://openai.com/careers/applied-ai-engineer-codex-core-agent-san-francisco/
- Anthropic, Applied AI Engineer, Enterprise Tech: https://job-boards.greenhouse.io/anthropic/jobs/5057647008
- Quizlet, Applied AI Engineer: https://jobs.lever.co/quizlet-2/06b08f64-cb41-4bf1-97fc-787c71c24e02
- Arcana Analytics, Senior AI Engineer - Inference & Agent Systems: https://job-boards.greenhouse.io/arcanaanalytics/jobs/4183986009
- Lever application form fields: https://help.lever.co/hc/en-us/articles/20087243347741-Configuring-your-Lever-Application-Form
- Ashby application form fields: https://docs.ashbyhq.com/application-forms

## Data Categories

### Candidate Identity

Private by default:

- Legal name.
- Preferred name.
- Email.
- Phone.
- Current location.
- Address, if needed for applications.
- Time zone.

Public only if approved:

- Display name.
- General location, such as city/region or remote preference.
- Public contact CTA.

### Links and Public Presence

- LinkedIn.
- GitHub.
- Portfolio.
- Personal website.
- Published writing.
- Talks or demos.
- Open-source projects.

Each link should have visibility, verification status, and source metadata.

### Target Role Intent

This should be one of the first things the intake agent asks:

> What do you want to do next?

Structured fields:

- Target titles.
- Target role families.
- Target seniority.
- Target industries or domains.
- Preferred company stage or size.
- Preferred work mode: remote, hybrid, onsite.
- Preferred locations.
- Constraints and dealbreakers.
- Optional compensation expectations.
- Optional availability or earliest start date.

Compensation and availability should be private unless explicitly approved for a specific use.

### Experience Containers

These are not single facts. They are structured sources that can produce many profile facts.

- Jobs.
- Contracts.
- Consulting engagements.
- Projects.
- Education.
- Certifications.
- Publications.
- Talks.
- Open-source contributions.
- Awards.
- Volunteer or community work.

Each experience should capture:

- Title.
- Organization.
- Start and end dates.
- Location or remote context.
- Summary.
- Responsibilities.
- Outcomes.
- Technologies used.
- Relevant artifacts or links.
- Whether it is public.
- Whether details are verified, candidate-provided, resume-derived, or inferred.

### Profile Facts

Profile facts are atomic claims that may be used by the public candidate agent after review.

Examples:

- "Built a production FastAPI service for X."
- "Used Python in Y project."
- "Led migration from A to B."
- "Created eval cases for LLM regression testing."
- "Earned degree Z from institution Q."

Each fact should include:

- Fact type.
- Claim text.
- Structured value where possible.
- Source.
- Source artifact.
- Evidence links.
- Visibility.
- Verification status.
- Human approval status.
- Created/updated timestamps.

### Skill Claims

Skills are not just tags. They should be structured claims with evidence.

Recommended fields:

- Skill name.
- Skill category.
- Years experience as a range or lower bound, not false precision.
- Last used date or recency.
- Proficiency level.
- Evidence facts.
- Related experiences.
- Confidence.
- Verification status.
- Visibility.

Example:

```text
Python
Category: programming language
Years: 4-6
Recency: current
Evidence: job X, project Y, repo Z
Verification: human-approved
Visibility: public
```

Skill categories for Applied AI profiles:

- Programming languages.
- Backend/API engineering.
- Frontend/product engineering.
- Databases and data modeling.
- Cloud and deployment.
- LLM APIs.
- Prompting and context construction.
- Agent design and tool use.
- RAG and retrieval.
- Evals and regression testing.
- Observability and monitoring.
- ML frameworks.
- Data engineering.
- Security and safety.
- Domain expertise.
- Communication and customer-facing work.

### Sensitive and Application-Only Data

These fields may matter for applications, but should not power the public profile unless explicitly approved:

- Address.
- Phone.
- Work authorization.
- Visa sponsorship needs.
- Relocation willingness.
- Earliest start date.
- Interview timeline.
- Compensation expectations.
- Private references.
- Private application notes.

Voluntary EEO/demographic fields should not be part of the core candidate profile or role-fit agent context. If ever collected, they should be isolated for compliance purposes and not used for matching, scoring, public display, or application positioning.

## Evidence and Verification Levels

Every extracted detail should carry provenance.

Recommended levels:

- `resume`: extracted from an uploaded or pasted resume.
- `chat`: provided in conversation or form input.
- `model`: inferred by the model and requiring extra review.
- `artifact_supported`: supported by a link, repo, document, demo, or certificate.
- `human_verified`: reviewed and approved by the candidate.
- `published`: allowed to power the public candidate-agent profile.
- `inferred`: generated from other facts and never treated as a verified fact by itself.

The public portfolio agent can use only facts that are both human-approved and public.

## Command-Center Tooling

Profile intake is now the first real JobOps command-center tool.

The primary flow is:

1. The user enters natural language in the AI Command Center.
2. Next.js sends the command through a thin proxy.
3. FastAPI interprets the command.
4. Profile-related commands route to `profile_intake`.
5. FastAPI executes the existing profile intake workflow.
6. FastAPI returns the assistant message, action result, target workspace, and saved draft snapshot.
7. The Profile tab displays the updated saved draft as a review surface.

The Profile tab should not own a separate chat composer. It should tell the user:

> Use the JobOps command center above to update your profile.

FastAPI remains responsible for model calls, Pydantic validation, artifacts, draft persistence, and tool routing. Next.js must not call the model directly.

Profile-intake is stateful from the backend's perspective. Each model call receives the database-loaded saved draft as `authoritative_current_draft`; browser-provided `existing_draft` is optional UI/debug context and is not authoritative. The durable memory for intake is the saved draft/profile state in Postgres, not client state and not LLM chat history.

Profile-intake persistence is merge-based. Each successful model turn is treated as a patch to the active saved draft, not as a complete replacement. Empty model sections such as `draftFacts: []`, empty strings, null fields, or omitted optional role-target values mean "no change" for existing saved data. They must not clear previously saved role intent, draft facts, skills, experience/project drafts, evidence links, review state, visibility, or publication state.

The model should preserve existing values unless the latest user message explicitly changes or removes them. The model, not the persistence layer, is responsible for semantically merging the latest user message into the authoritative current draft. For `targetRoleIntent`, any non-empty field returned by the model is treated as the final post-update saved value for that field, not a delta. If the user broadens a preference, including terse wording like "or NYC or San Francisco Bay", the model should append or merge with existing preferred locations, target titles, role families, domains/industries, skills, evidence links, and projects. Replacement language such as "instead", "not X anymore", "change X to Y", "remove X", and "clear X" may update or remove values only when explicit.

For now, some list-like target role fields remain strings. A location update may be represented as `Louisville, KY; London, UK` rather than a JSON array. TODO: move list-like target role intent fields to structured arrays once the database and UI can support that cleanly.

Explicit delete, clear, or reset behavior is deferred. It should require intentional user action and a separate persistence path so the system can distinguish "the model found nothing new" from "the user deliberately removed saved profile data."

Published profile rows must not be edited directly by profile intake. If profile changes are requested after the most recent profile state has been published and no active draft exists, JobOps should start a new private draft based on the published profile by default, or eventually ask whether to start from scratch versus from previous published values. The current backend seeds an unpublished draft copy for published role targets and published profile facts; broader published-profile edit semantics and UI choice remain deferred.

## Intake Workflow

### 1. Start With Intent

The intake agent starts from the command center with:

> What do you want to do next?

It should collect target titles, role families, seniority, domains, constraints, and preferred work mode before deciding which details to draw out.

### 2. Optional Resume Upload

The user may upload a resume to prefill:

- Identity.
- Contact details.
- Work history.
- Education.
- Skills.
- Projects.
- Links.
- Dates.

Resume-derived facts should become drafts, not verified facts.

### 3. Role-Lens Selection

The agent uses the user's target role to choose one or more role lenses.

Initial Applied AI lenses:

- Applied AI product engineer.
- Forward deployed AI engineer.
- LLM/agent systems engineer.
- AI evals and reliability engineer.
- RAG/retrieval engineer.
- ML/product ranking engineer.
- AI infrastructure/inference engineer.

Each lens has different follow-up priorities.

### 4. Gap-Aware Follow-Up

The agent compares resume-derived details to target role expectations and asks questions that draw out missing evidence.

Examples:

- "Tell me about an AI or automation feature you shipped beyond a prototype."
- "Have you built evals, test harnesses, or regression checks for model behavior?"
- "What production constraints did you handle: latency, cost, reliability, monitoring, safety, or failure recovery?"
- "Which projects show your Python/backend depth?"
- "Have you worked directly with users, customers, stakeholders, or business teams to shape requirements?"
- "Do you have public artifacts: GitHub repos, demos, writing, talks, or case studies?"

### 5. Draft Structured Facts

After each answer, the agent proposes structured facts:

- Claim.
- Category.
- Evidence.
- Suggested visibility.
- Confidence.
- Follow-up questions.

The user can approve, edit, reject, or mark private.

### 6. Human Review and Publication

No fact becomes verified or public without human review.

The workflow should separate:

- Draft profile data.
- Human-approved private facts.
- Human-approved public facts.
- Published profile facts.

### 7. Role-Fit Reuse

The same verified facts should power:

- Public candidate Q&A.
- Role-fit analysis.
- Application packet drafts.
- Interview preparation.
- Follow-up reminders.

## Initial Q&A Script

The first version of the intake agent can use this sequence:

1. What do you want to do next?
2. Do you want to upload a resume to prefill your profile?
3. Which roles are you targeting first?
4. What kinds of companies or domains are most interesting?
5. Which projects or jobs best prove you can do this work?
6. What have you shipped that used AI, automation, data, or agents?
7. What technical stack do you want recruiters to associate with you?
8. What production constraints have you handled?
9. What outcomes can we quantify?
10. Which facts are safe to publish publicly?

## Design Implications

Add data structures for:

- Resume artifacts.
- Intake sessions.
- Intake messages or redacted intake events.
- Draft facts.
- Fact review states.
- Skill claims.
- Role targets.
- Evidence artifacts.

Avoid storing raw chat forever by default. Keep structured facts, redacted events, and user-approved source artifacts.
