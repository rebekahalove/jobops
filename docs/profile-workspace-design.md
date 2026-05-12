# Conversation-First Profile Workspace Design

This document defines the revised direction for the JobOps Profile workspace. The current form-first prototype is useful for testing profile concepts, but the intended product experience is conversation-first: the user should talk to an intake agent, optionally attach a resume, and review structured profile data below the conversation.

## 1. Conversation-First Profile Workspace UX

The Profile workspace should open with a large intake/chat panel at the top of the page.

The primary input should be prefilled with:

```text
I want to be a...
```

The user can complete that sentence, add more context, paste resume text directly into the chat, or attach a resume using an upload affordance similar to ChatGPT: a compact attachment button near the message input, clear file state, and no separate form-first upload workflow.

After each message or resume attachment, the agent should:

- Extract target role intent from the conversation.
- Update structured profile draft data.
- Create draft facts, skill claims, and experience summaries.
- Ask targeted clarifying questions.
- Summarize what changed in the profile draft.

The structured profile review area should remain below the chat, but it is a review, edit, and verification surface. It should not be the primary intake method.

Recommended page order:

1. Conversation and resume intake panel.
2. "What changed" summary from the latest agent turn.
3. Structured profile review sections.
4. Review queues grouped by information type.
5. Clarifying questions and suggested next prompts.

## 2. Profile Data Model

The Profile workspace should prepare the following concepts without over-modeling the first local shell.

`candidate_profile`

- The candidate's durable profile record.
- Owns identity, positioning summary, profile completeness state, publication state, and relationships to facts, skills, experiences, artifacts, and target role intent.

`target_role_intent`

- What the candidate wants next.
- Includes target titles, role families, seniority, domains, company preferences, work mode, locations, constraints, dealbreakers, and positioning goals.

`experience_container`

- A larger source of profile claims, such as a job, project, contract, education record, certification, publication, talk, or open-source contribution.
- Containers group many facts and skill claims so the UI does not become a flat pile of assertions.

`atomic_profile_fact`

- A single claim that can be reviewed, verified, rejected, made private, or eventually published.
- Examples: "Built a FastAPI service for X", "Created LLM eval cases", or "Earned degree Y from institution Z."

`skill_claim`

- A structured claim about a skill, backed by evidence.
- Should include skill name, category, proficiency or confidence, approximate years or recency where appropriate, related facts, related experiences, and verification state.

`evidence_artifact`

- A supporting source such as a GitHub repo, demo, writing sample, certificate, resume section, portfolio page, or uploaded document reference.
- Evidence has its own visibility and access rules.

`resume_artifact`

- Metadata and parsed structure for an uploaded or pasted resume.
- Resume-derived details become draft data only; the raw resume should not be stored permanently by default.

`intake_session`

- A bounded profile setup or refinement session.
- Tracks active target role lens, attached artifacts, draft changes, agent summaries, and unresolved questions.

`intake_message` or `redacted_event`

- A conversation turn or safe event record.
- Prefer redacted events and structured summaries over storing raw chat forever.

`field_revision` or `change_event`

- A field-level or fact-level change record.
- Captures what changed, source, actor, timestamp, prior verification state, and whether re-review is required.

## 3. Verification And Visibility Model

Use separate statuses for source, review, visibility, and publication. Canonical code values should use snake_case; UI labels can render them in friendlier text.

Source and derivation:

- `model_drafted`: proposed by the agent or model.
- `resume`: extracted from a pasted or uploaded resume.
- `chat`: extracted from user conversation.
- `model`: inferred by the model and requiring extra review.
- `user_edited`: directly edited by the user.

Review:

- Review status depends on scope. Core sections, list items, and the whole profile each have separate status values defined below.

Visibility:

- `private`: available only inside the private JobOps workspace.
- `application_only`: allowed for selected application materials, not public profile responses.
- `public`: approved for use in public-facing candidate-agent context.

Publication:

- `unpublished`: not currently used by the public candidate-agent profile.
- `published`: actively included in the public candidate-agent profile.

Rules:

- Model-generated, resume-derived, and chat-derived data must not become verified automatically.
- Resume-derived data must not become public automatically.
- Manual user edits may become `user_verified` private data, but should still require a deliberate verification action.
- Public visibility requires a separate explicit action from verification.
- Publication requires a separate explicit action from public visibility.
- Rejected data should remain available for audit or undo while excluded from agent context and generation.

## 3.1 Review Status And Action Model

The Profile workspace has three different review scopes. They should not be collapsed into one generic "approval" concept.

### Core Profile Sections

Core profile sections are stable structured fields reviewed at the section level:

- Identity & Contact.
- Target Role Intent.
- Work Authorization & Mobility.
- Location / Work Preferences.
- Compensation & Constraints.
- Links / Public Presence.

Core sections support section-level review:

- Approve section.
- Reject generated changes.
- User edits fields directly.

Manual edits should mark the section as `Edited by you` / `Needs review`. Manual edits are not the same as rejection.

Approving a core section means the section becomes verified private data. It does not make the section public, public-ready, or published.

Core section statuses:

| Status | Meaning |
| --- | --- |
| `empty` | No known data yet. |
| `agent_draft` | Generated from model, resume, or chat input and not reviewed. |
| `edited_by_you` | User directly changed at least one field. |
| `needs_review` | Requires user review before it can be trusted as verified private data. |
| `verified_private` | Approved for private JobOps use. |
| `needs_re_review` | Previously verified data changed and needs another review. |
| `rejected` | Generated changes were rejected. |

### Review Queue Items

Review queue items are repeatable records reviewed item by item:

- Experience & Projects.
- Education.
- Certifications.
- Skills.
- Achievements / Outcomes.
- Profile Facts / Claims.
- Evidence Artifacts.
- Publications / Writing / Talks.
- Open-source Contributions.

Review queue items support item-level review:

- Edit.
- Approve.
- Reject.
- Later: mark public-ready / publish. Do not implement publishing yet.

List item statuses:

| Status | Meaning |
| --- | --- |
| `draft` | Proposed item that has not been reviewed. |
| `edited` | User changed the item after it was drafted or verified. |
| `verified_private` | Approved for private JobOps use. |
| `public_ready` | Approved as safe to use in public contexts, but not published yet. |
| `published` | Included in the public candidate-agent profile. |
| `rejected` | Removed from active profile use. |

### Whole Profile

Whole-profile status is a summary. It does not replace field-level, section-level, or item-level status.

Whole-profile status dimensions:

| Dimension | Values | Meaning |
| --- | --- | --- |
| Review | `needs_verification`, `verified` | Whether the profile has unresolved review work. |
| Visibility | `private`, `public_ready` | Whether data has been approved for public use. |
| Publication | `not_published`, `published` | Whether public-ready data is actually live. |

### Actions By Status

Core profile section actions:

| Status | Available actions |
| --- | --- |
| `empty` | Edit, add via conversation. |
| `agent_draft` | Approve section, reject generated changes, edit. |
| `edited_by_you` | Approve section, continue editing. |
| `needs_review` | Approve section, reject generated changes, edit. |
| `verified_private` | Edit. |
| `needs_re_review` | Approve section, edit, reject latest generated changes. |
| `rejected` | Restore / regenerate later. |

Review queue item actions:

| Status | Available actions |
| --- | --- |
| `draft` | Edit, approve, reject. |
| `edited` | Approve, continue editing, reject. |
| `verified_private` | Edit, later mark public-ready. |
| `public_ready` | Edit, later publish. |
| `published` | Edit, unpublish later. |
| `rejected` | Restore / regenerate later. |

Whole-profile actions:

| Status dimension | Available actions |
| --- | --- |
| Review: `needs_verification` | Continue review, approve eligible sections/items. |
| Review: `verified` | Edit profile, run another intake pass. |
| Visibility: `private` | Review candidates for public-ready status later. |
| Visibility: `public_ready` | Publish later. |
| Publication: `not_published` | Publish only after explicit public-ready review. |
| Publication: `published` | Unpublish or update later. |

### Review Queue Layout

Review queues should be grouped by information type, not by status. Avoid cards named after workflow states such as "approved facts" or "public facts."

Recommended queue groups:

- Experience & Projects.
- Education.
- Certifications.
- Skills.
- Achievements / Outcomes.
- Facts / Claims.
- Evidence & Links.

Each item should show status with compact badges, colored dots, or icons. Actions should stay compact and status-dependent. Do not add broad action bars or large button groups before the status model is implemented.

Publishing is intentionally deferred. Public-ready and published states should exist in the model, but the MVP shell should not implement publish behavior yet.

## 4. Field-Level Change Indicators

The review UI should show status at the field or fact level, not only at the page level.

Required indicators:

- Model changed this field: show an "Agent draft" or "Suggested change" badge and include the latest change summary.
- User edited this field: show an "Edited by you" badge and update the revision history.
- Field needs review: show a "Needs review" badge and keep it out of public profile context.
- Field is verified: show a "Verified" badge with the verification timestamp or actor when available.
- Field changed after verification: show "Needs re-review" and remove it from verified/public use until accepted again.

Useful UI behaviors:

- Highlight changed fields after each agent turn.
- Offer accept, edit, reject, and mark private actions on suggested facts.
- Show a compact diff for changed stable fields.
- Keep a revision drawer or history panel available for higher-risk fields.

## 5. Relationship Between Fields And Facts

Stable profile fields are the current best structured values for common profile surfaces: name, headline, target role intent, location preference, links, summary, and selected profile highlights.

Experience containers are larger records that organize work, projects, education, publications, and other sources of evidence. They are not atomic facts by themselves.

Atomic facts are individual claims extracted from experiences, resumes, chat, or artifacts. They are the safest unit for verification and grounding because each can carry provenance, evidence, review state, and visibility.

Skill claims are structured assertions about capabilities. A skill should not be just a tag; it should link back to facts, experiences, and evidence.

Evidence artifacts are supporting materials. They can support many facts and skill claims.

To avoid a giant unusable form, the UI should not render every fact as a permanent field. Instead:

- Show stable profile fields in compact editable sections.
- Group experience containers into expandable cards or rows.
- Put atomic facts into review queues grouped by source, experience, skill, and verification status.
- Use filters such as "new drafts", "needs re-review", "public candidates", and "application-only".
- Show the most relevant facts under each experience or skill, with the full list available through drill-down.
- Let the conversation guide the user to unresolved gaps instead of making the user scan every possible field.

## 6. Implementation Plan

Revise the current Profile page in small steps:

1. Convert the top of `/profile` into a large conversation-first intake panel.
2. Prefill the message input with `I want to be a...`.
3. Add a local resume attachment/upload affordance without real upload or persistence.
4. Replace the current "Generate draft profile" form-first action with a conversation turn processor.
5. Keep all state local in the browser for now.
6. Keep the current target role, draft facts, skill claims, experience summaries, and clarifying questions as local review shapes.
7. Move structured fields below the chat as review/edit/verification sections.
8. Add a "what changed" summary after each mocked agent turn.
9. Add section-level, item-level, and whole-profile status badges using the review model above.
10. Update tests to cover the chat-first panel, prefilled input, attachment affordance, mocked extraction, and structured review sections.

Do not add yet:

- Database persistence.
- Real resume upload storage.
- Authentication.
- Full agent loop.
- Job intake, fit scoring, materials generation, or application tracking.

Current implementation status: the Profile shell follows this conversation-first layout and calls the FastAPI profile-intake endpoint through a thin Next.js proxy. FastAPI owns prompt construction, provider selection, model calls, Pydantic validation, artifact saving, and debug logging. The UI still keeps draft profile state locally and renders information-type review queues without approval/publish controls.

Recommended next implementation step: persist validated draft output in the FastAPI/database boundary as an intake session and draft profile change event, while keeping human verification and publication as explicit later actions.
