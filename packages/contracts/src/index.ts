export type VerificationStatus = "draft" | "candidate_approved" | "published";

export type Visibility = "private" | "public";

export type ProfileFact = {
  id: string;
  claim: string;
  category: string;
  source: string;
  visibility: Visibility;
  verificationStatus: VerificationStatus;
};

export type CandidateProfile = {
  id: string;
  slug: string;
  displayName: string;
  headline: string;
  summary: string;
  profileStatus: "draft" | "published";
  facts: ProfileFact[];
  updatedAt: string;
};

export type CandidateAnswer = {
  answer: string;
  verifiedFactsUsed: string[];
  inferences: string[];
  unknowns: string[];
  caveats: string[];
};

export type RoleFitAnalysis = {
  fitScore: number;
  fitSummary: string;
  matchingStrengths: string[];
  gapsOrConcerns: string[];
  suggestedApplicationPositioning: string;
  recommendedNextStep: string;
  suggestedInterviewQuestions: string[];
  evidence: string[];
  caveats: string[];
};
