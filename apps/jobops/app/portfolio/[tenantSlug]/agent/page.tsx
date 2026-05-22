import { AgentWorkspace } from "../../../../../portfolio/components/agent-workspace";
import { loadTenantPortfolioProfile } from "../../../../lib/tenant-portfolio";

export const dynamic = "force-dynamic";

export default async function TenantAgentPage({ params }: { params: Promise<{ tenantSlug: string }> }) {
  const { tenantSlug } = await params;
  const { profile, source } = await loadTenantPortfolioProfile(tenantSlug);

  return <AgentWorkspace backHref={`/portfolio/${tenantSlug}`} profile={profile} source={source} />;
}
