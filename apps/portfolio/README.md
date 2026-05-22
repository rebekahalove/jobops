# JobOps Portfolio App

Public candidate-agent portfolio for `rebekahalove.dev`.

Alpha route status:

- `/` and `/portfolio` render the public portfolio for the request hostname.
- `/portfolio/[tenantSlug]` renders an alpha tenant portfolio by tenant or profile slug.
- The embedded candidate-agent posts to the local Next route at `/api/public/candidate-agent`, which calls FastAPI server-side.
- Public candidate-agent answers must be grounded only in published public profile data returned by the API.
- Local development may use the seed profile when the API is unavailable. Production shows a generic unavailable state and logs diagnostics server-side.
- The separate `/portfolio/.../agent` page is intentionally not present; chat is embedded in the portfolio page.
- Does not include auth, scraping, email, ATS integration, or public rate limiting yet.
- Does not include auth, scraping, email, or ATS integration.

Run from the repo root:

```powershell
corepack pnpm install
corepack pnpm dev
```
