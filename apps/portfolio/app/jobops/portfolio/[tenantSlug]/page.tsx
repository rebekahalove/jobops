import { PublicPortfolio } from "../../../../components/public-portfolio";
import { loadTenantPortfolioProfile } from "../../../../lib/profile";

export const dynamic = "force-dynamic";

export default async function TenantPortfolioPage({ params }: { params: Promise<{ tenantSlug: string }> }) {
  const { tenantSlug } = await params;
  const { profile, source } = await loadTenantPortfolioProfile(tenantSlug);

  return <PublicPortfolio agentHref={`/jobops/portfolio/${tenantSlug}/agent`} profile={profile} source={source} />;
}
