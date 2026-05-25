import { PublicAlphaLanding } from "../../components/public-alpha-landing";
import { getCurrentJobOpsSession } from "../../lib/jobops-session";
import { getPublicJobOpsMetrics } from "../../lib/public-jobops";

export const dynamic = "force-dynamic";

export default async function AboutJobOpsPage() {
  const [metrics, session] = await Promise.all([getPublicJobOpsMetrics(), getCurrentJobOpsSession()]);
  return <PublicAlphaLanding auth={session} initialMetrics={metrics} />;
}
