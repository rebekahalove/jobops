import { PublicPortfolio } from "../../../portfolio/components/public-portfolio";
import { loadCandidateProfile } from "../../../portfolio/lib/profile";

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  const { profile, source } = await loadCandidateProfile();

  return <PublicPortfolio profile={profile} source={source} />;
}
