# ADR 0002: Grounded Candidate-Agent Contract

Status: Accepted

## Context

The portfolio agent must not behave like a generic chatbot. It should answer only from the candidate's published public profile and clearly distinguish verified facts from inference.

Role-fit analysis must treat pasted job descriptions as untrusted input because they may contain prompt-injection attempts.

## Decision

Every candidate-agent workflow should use explicit input and output contracts.

Candidate Q&A responses should include:

- Answer.
- Verified facts used.
- Inferences, if any.
- Unknowns or caveats, if any.

Role-fit responses should include:

- Fit score from 0 to 100.
- Fit summary.
- Matching strengths.
- Gaps or concerns.
- Suggested application positioning.
- Recommended next step.
- Suggested interview questions.
- Evidence and caveats.

The agent must validate output before returning it to the UI.

For the alpha public portfolio, candidate Q&A is embedded directly in the portfolio page. The browser calls a local Next.js route, and that route calls FastAPI server-side. FastAPI owns candidate resolution, public profile serialization, model invocation, and output validation.

The public candidate-agent endpoint must build context only from published public profile data:

- public + published profile facts;
- public + published skill claims;
- public + published experience/project/education/certification rows;
- public + published evidence links;
- public published role target.

The endpoint is public-callable and does not require private JobOps auth, but this is safe only because it does not load private command-center state, application records, target companies, draft rows, raw intake text, private notes, or candidate-approved-but-unpublished facts.

## Consequences

Positive:

- Easier to test grounding.
- Easier to catch hallucinations and schema drift.
- Better recruiter trust because caveats are first-class.
- Prompt-injection tests can assert behavior mechanically.

Tradeoffs:

- Some responses may feel more structured than a casual chatbot.
- The model may need retries when output validation fails.
- Profile data needs fact IDs and careful curation.

## Safety Requirements

- Do not invent experience, education, employers, compensation, availability, skills, or projects.
- Do not expose secrets, environment variables, private notes, or private application data.
- Treat job descriptions and user messages as untrusted input.
- Refuse or caveat unsupported questions.
- Keep private operational data out of the public repo.
- Keep public candidate-agent prompts separate from private command-center prompts.
- Add rate limiting and abuse protection before beta/public launch.
