# ADR 0004: Netlify, Render, and Neon as Initial Hosting Split

Status: Accepted

## Context

JobOps should start on hosting that is free or under $10/month before model API usage and domain registration.

The selected platforms should also be plausible for professional client work, support CI/CD, and support infrastructure-as-code where practical. The first deployment should not require the project to spend its complexity budget on low-level hosting operations.

The application shape is:

- Next.js frontends in `apps/portfolio` and `apps/jobops`.
- FastAPI backend in `services/api`.
- Postgres database managed by Neon.

## Decision

Use:

- Netlify for the Next.js frontends.
- Render for the FastAPI backend.
- Neon Postgres for the database.
- GitHub Actions for CI.

Initial expected baseline cost:

```text
Netlify Free      $0/month
Render Starter    about $7/month
Neon Free         $0/month
```

This keeps the hosting baseline under $10/month, excluding model API usage and domain registration.

## Why Netlify

Netlify is preferred for the frontends because:

- The user has prior experience with it.
- It supports CI/CD and deploy previews.
- It supports custom domains and managed TLS.
- It supports file-based configuration with `netlify.toml`.
- It supports Next.js through OpenNext.

## Why Render Over Fly.io For The First API Host

Render is preferred for the first FastAPI API host because:

- It is a lower-operations platform for a small Python web service.
- It supports straightforward Git-based FastAPI deploys.
- It provides environment variables, logs, custom domains, managed TLS, and service previews.
- It supports infrastructure-as-code through `render.yaml`.
- The Starter web service cost is predictable enough for the under-$10/month target.

Fly.io remains a strong future option. It may become preferable if JobOps needs:

- More control over regions and runtime placement.
- Container-first operations.
- Deeper control over Machines, autostop/autostart, or scaling behavior.
- More infrastructure learning or platform control as an explicit project goal.

For the first hosted API, Render better matches the goal of shipping a production-shaped service without making hosting itself the main project.

## Consequences

Positive:

- The deployment story stays easy to explain and operate.
- The frontends and backend can scale independently.
- The project keeps Netlify familiarity while still using a real Python API host.
- Hosting cost stays low enough for a serious MVP.

Tradeoffs:

- The system uses three managed platforms instead of one.
- Cross-platform environment management needs discipline.
- Render's free tier sleeps, so the public API should use a paid Starter service before serious recruiter traffic.
- Fly.io would provide more infrastructure control, but that control is not needed yet.

