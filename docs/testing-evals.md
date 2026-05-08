# Testing and Eval Strategy

## Testing Pyramid

The MVP should combine conventional tests with AI-specific regression checks.

## Conventional Tests

Unit tests:

- Candidate profile schema validation.
- Role-fit response schema validation.
- Prompt rendering.
- Context construction from profile facts.
- Safety post-processing helpers.
- Score bounds and output parsing.
- Domain-to-candidate resolution rules.
- Tenant-scoped data access helpers.

Integration tests:

- FastAPI health check and settings loading.
- Alembic migrations against a fresh Postgres database.
- Candidate profile API with seeded data.
- Candidate Q&A endpoint with a mock model adapter.
- Role-fit endpoint with a mock model adapter.
- Output validation failures.
- Missing or malformed profile data.
- Environment variable handling without exposing values.
- Tenant isolation for profile and JobOps records.

Browser tests:

- Landing page renders.
- Candidate-agent interface opens.
- User can submit a question.
- User can submit a job description.
- Error states are visible and non-leaky.

Frontend tests:

- Generated TypeScript API client compiles.
- Portfolio app handles backend errors safely.
- Private dashboard shell does not expose data without approved access-control work.

## Eval Cases

Store public, sanitized eval cases in `packages/evals/cases`.

Candidate Q&A eval categories:

- Directly supported factual questions.
- Partially supported questions.
- Unsupported questions that should be caveated.
- Questions about compensation, availability, or private data.
- Questions that require distinguishing verified facts from inference.

Role-fit eval categories:

- Strong-fit technical role.
- Partial-fit technical role.
- Low-fit role.
- Ambiguous job description.
- Job description with conflicting requirements.

## Eval Assertions

Use deterministic assertions first:

- Response matches schema.
- Required fields are present.
- Fit score is between 0 and 100.
- Unsupported claims are absent for known cases.
- Required caveat text or unknown markers appear when expected.
- No forbidden secret or environment-variable patterns appear.

Use LLM-as-judge only as a secondary signal:

- Grounding quality.
- Helpfulness.
- Role-fit reasoning clarity.
- Tone and recruiter usefulness.

Live-model evals should be budgeted and can run on demand or nightly. PR checks should be deterministic and able to run without an API key.

## Regression Policy

- Every fixed hallucination or prompt-injection failure gets a regression case.
- Every new public profile section gets at least one Q&A eval.
- Every prompt version change runs the full eval suite.
- Role-fit scoring changes require before-and-after eval reports.
- Every new tenant-scoped data access pattern gets an isolation test.
