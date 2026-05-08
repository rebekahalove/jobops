# ADR 0001: Monorepo With Separate Apps, Backend, and Shared Platform Packages

Status: Accepted

## Context

JobOps includes both a public candidate-agent portfolio and a private job-search operations dashboard. The first public tenant is Rebekah Love, served at `rebekahalove.dev` with a private dashboard at `jobops.rebekahalove.dev`.

The product should naturally grow to support invited candidates, multiple profile pages, private application histories, and custom or JobOps-hosted domains.

The repo may be public, so committed data must be safe for public exposure.

## Decision

Use a monorepo with:

- `apps/portfolio` for `rebekahalove.dev`.
- `apps/jobops` for `jobops.rebekahalove.dev`.
- `services/api` for the FastAPI backend.
- `packages/contracts` for generated API types and shared contracts.
- `packages/profile` for approved public seed profile data and profile helpers.
- `packages/prompts` for prompt templates.
- `packages/evals` for regression evals.
- `packages/security-harness` for prompt-injection and adversarial checks.

Use Neon Postgres as the production source of truth for managed platform data. Approved public profile seed data may be committed for reviewability, bootstrapping, and eval fixtures.

## Consequences

Positive:

- Public and private product surfaces remain distinct.
- Shared AI safety and eval tooling can mature independently of the UI.
- Profile grounding can be tested without relying only on prompt wording.
- The repo can grow into a professional applied-AI project without an early rewrite.
- Rebekah's deployment can be the first tenant rather than a one-off app.

Tradeoffs:

- More initial structure than a single Next.js app or static portfolio.
- The repo uses both Node and Python toolchains.
- Requires discipline to avoid overbuilding packages before they have real behavior.
- Requires explicit data-boundary practices because the repo is public.

## Alternatives Considered

Single Next.js app:

- Faster for a prototype.
- Weaker fit for reusable eval and safety packages.
- Easier to blur public and private concerns.

Static JSON-only data:

- Simple for the first public page.
- Poor fit once candidates, applications, saved analyses, usage metrics, and CRUD workflows exist.
- Would create migration pressure immediately after the prototype succeeds.
