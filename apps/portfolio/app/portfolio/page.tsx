import { PublicPortfolio } from "../../components/public-portfolio";
import { loadCandidateProfile } from "../../lib/profile";

export default async function PortfolioPage() {
  const { profile, source } = await loadCandidateProfile();

  return <PublicPortfolio profile={profile} source={source} />;
}
