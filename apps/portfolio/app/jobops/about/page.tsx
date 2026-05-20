import { PublicAlphaLanding } from "../../../../jobops/components/public-alpha-landing";
import { getPublicJobOpsMetrics } from "../../../../jobops/lib/public-jobops";

export const dynamic = "force-dynamic";

export default async function AboutJobOpsPage() {
  const metrics = await getPublicJobOpsMetrics();
  return <PublicAlphaLanding basePath="/jobops" initialMetrics={metrics} />;
}
