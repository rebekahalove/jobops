import { PublicAlphaLanding } from "../../../../jobops/components/public-alpha-landing";
import { getCurrentJobOpsSession } from "../../../../jobops/lib/jobops-session";
import { getPublicJobOpsMetrics } from "../../../../jobops/lib/public-jobops";

export const dynamic = "force-dynamic";

export default async function AboutJobOpsPage() {
  const [metrics, session] = await Promise.all([getPublicJobOpsMetrics(), getCurrentJobOpsSession()]);
  return <PublicAlphaLanding auth={session} basePath="/jobops" initialMetrics={metrics} />;
}
