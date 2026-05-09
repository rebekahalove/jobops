import { AgentWorkspace } from "../../components/agent-workspace";
import { loadCandidateProfile } from "../../lib/profile";

export default async function AgentPage() {
  const { profile, source } = await loadCandidateProfile();

  return <AgentWorkspace profile={profile} source={source} />;
}
