import { PublicAlphaLanding } from "../../components/public-alpha-landing";
import { getPublicJobOpsMetrics } from "../../lib/public-jobops";

export const dynamic = "force-dynamic";

export default async function AboutJobOpsPage() {
  const metrics = await getPublicJobOpsMetrics();
  return <PublicAlphaLanding initialMetrics={metrics} />;
}
