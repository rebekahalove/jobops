# Initial Repo Structure

Recommended structure after approval:

```text
.
|-- apps/
|   |-- portfolio/
|   |   |-- app/
|   |   |-- components/
|   |   |-- lib/
|   |   |-- tests/
|   |   `-- README.md
|   `-- jobops/
|       |-- app/
|       |-- components/
|       |-- lib/
|       |-- tests/
|       `-- README.md
|-- services/
|   `-- api/
|       |-- alembic/
|       |-- jobops_api/
|       |   |-- agents/
|       |   |-- db/
|       |   |-- routers/
|       |   |-- services/
|       |   |-- settings.py
|       |   `-- main.py
|       |-- tests/
|       |-- alembic.ini
|       |-- pyproject.toml
|       `-- README.md
|-- packages/
|   |-- contracts/
|   |   |-- src/
|   |   `-- tests/
|   |-- profile/
|   |   |-- data/
|   |   |   `-- rebekah-love.public.seed.json
|   |   |-- src/
|   |   `-- tests/
|   |-- prompts/
|   |   |-- src/
|   |   `-- tests/
|   |-- evals/
|   |   |-- cases/
|   |   |-- src/
|   |   `-- tests/
|   `-- security-harness/
|       |-- cases/
|       |-- src/
|       `-- tests/
|-- docs/
|   |-- adr/
|   |-- runbooks/
|   `-- planning/
|-- .github/
|   `-- workflows/
|-- .env.example
|-- .gitignore
|-- package.json
|-- pnpm-workspace.yaml
|-- tsconfig.base.json
`-- README.md
```

## App Responsibilities

`apps/portfolio` owns the public experience at `rebekahalove.dev`:

- Landing page.
- Candidate-agent Q&A interface.
- Role-fit analysis workflow.
- Public profile rendering from backend profile data.
- Hostname-based candidate profile resolution.
- Public analytics events, if approved.

`apps/jobops` owns the private operations dashboard:

- Candidate profile setup via optional resume upload and Q&A interface with an agent, with human review before facts become verified or public.
- Target-company management.
- Application history.
- Saved role-fit analyses.
- Follow-ups and interview preparation.
- Human-approved application packet workflows later.
- No committed private operational data.

`services/api` owns backend behavior:

- FastAPI application.
- Local settings and environment loading.
- Neon Postgres access.
- SQLAlchemy models.
- Alembic migrations.
- Mock agent endpoints for the first local scaffold.
- Tenant and domain resolution.
- Candidate-agent Q&A endpoints.
- Role-fit analysis endpoints.
- Private JobOps CRUD when approved.
- OpenAPI contract generation.

Neon Postgres access, SQLAlchemy models, and Alembic migrations are part of the first database increment.

## Package Responsibilities

`packages/contracts` owns shared API and data contracts:

- JSON Schema contracts where cross-runtime validation is needed.
- Generated TypeScript types from the backend OpenAPI spec.
- Candidate-agent response contracts.
- Role-fit analysis contracts.
- Eval and security case contracts.

`packages/profile` owns public seed data and profile helpers:

- Approved public seed profile for Rebekah.
- Profile fixture data for evals and tests.
- Import helpers for seeding the database.
- No private operational data.

`packages/prompts` owns prompt templates:

- System prompts.
- Developer prompts.
- Role-fit analysis prompts.
- Prompt version metadata.

`packages/evals` owns regression evaluation:

- Public eval cases.
- Deterministic assertions.
- Optional live-model eval runner.
- Report generation.

`packages/security-harness` owns adversarial testing:

- Prompt-injection fixtures.
- Secret-exposure probes.
- Data-boundary tests.
- Refusal and caveat checks.

## Data Layout

Public approved profile seed data should start in:

```text
packages/profile/data/rebekah-love.public.seed.json
```

Production profile and JobOps data should live in Neon Postgres.

Private local scratch data may be untracked while exploring, but it should not become the CRUD data layer. Use ignored paths such as:

```text
data/private/
*.private.json
*.local.json
```

Once the app supports managing a data type through CRUD, that data type belongs in Postgres with an Alembic migration.
