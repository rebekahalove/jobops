export const runtime = "nodejs";
// Production mounts JobOps under rebekahalove.dev/jobops. Keep this wrapper in
// lockstep with apps/jobops/app/api so mounted API routes exist in portfolio.
export { GET } from "../../../../../../jobops/app/api/job-search-runs/[runId]/route";
