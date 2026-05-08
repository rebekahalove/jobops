# Day 1 Metrics

Metrics should be defined before instrumentation so the product does not drift into measuring only what is easy.

## Product Metrics

- Candidate profile page views by tenant and domain.
- Portfolio visit to agent-open rate.
- Agent question completion rate.
- Role-fit analysis start rate.
- Role-fit analysis completion rate.
- Recruiter CTA click rate.
- Repeat interaction rate within a session.
- Unknown-answer rate, tracked separately from failures.
- Future invitation activation rate.
- Future profile setup completion rate.

## Candidate-Agent Quality Metrics

- Grounded answer rate: percentage of answers fully supported by verified profile facts.
- Unsupported claim rate: percentage of outputs containing claims not supported by profile data.
- Correct caveat rate: percentage of unanswerable questions that receive a clear caveat or refusal.
- Fact citation coverage: percentage of substantive answers with fact references or evidence metadata.
- Output schema validity rate.
- Role-fit rubric consistency across repeated runs.
- Human review pass rate for sampled responses.

## Safety Metrics

- Prompt-injection bypass rate.
- Secret-exposure incident count.
- Private-data exposure incident count.
- Unsafe instruction compliance rate, which should remain 0.
- Refusal correctness for out-of-scope or unsupported requests.
- Job-description instruction isolation pass rate.

## Reliability Metrics

- API success rate by service endpoint.
- P50 and P95 latency for Q&A.
- P50 and P95 latency for role-fit analysis.
- Model timeout rate.
- Output validation failure rate.
- Retry rate.
- Cost per successful agent interaction.
- Database query latency for profile resolution and agent context loading.
- Alembic migration success rate in CI and deployment.

## Engineering Metrics

- CI pass rate.
- Unit and integration test pass rate.
- Eval pass rate.
- Adversarial smoke test pass rate.
- Build time.
- Deployment success rate.
- Dependency vulnerability count.

## Privacy Defaults

Do not log full free-form user questions or pasted job descriptions by default. Prefer event metadata, aggregate counts, latency, schema status, and explicit error categories.

If qualitative review is needed later, add a consent-aware sampling policy and redact job descriptions before storage.

In a multi-tenant system, every usage event must be scoped to a tenant or candidate profile and must avoid leaking one tenant's activity into another tenant's analytics.
