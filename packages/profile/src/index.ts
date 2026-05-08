import type { CandidateProfile } from "@jobops/contracts";
import rebekahLoveProfile from "../data/rebekah-love.public.seed.json";

export const publicProfile = rebekahLoveProfile as CandidateProfile;

export function getPublishedFacts(profile: CandidateProfile) {
  return profile.facts.filter(
    (fact) => fact.visibility === "public" && fact.verificationStatus === "published"
  );
}
