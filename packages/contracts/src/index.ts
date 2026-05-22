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
  targetRoleIntent?: {
    targetTitles?: string[];
    roleFamilies?: string[];
    preferredLocations?: string[];
    workModes?: string[];
    domainsOrIndustries?: string;
  };
  skillClaims?: Array<{
    id: string;
    skill: string;
    category: string;
    evidence?: string | null;
    yearsMin?: number | null;
    yearsMax?: number | null;
    visibility: Visibility;
    verificationStatus: VerificationStatus;
    publicationStatus: "not_published" | "published";
  }>;
  experienceAndProjects?: Array<{
    id: string;
    itemType: "experience" | "project" | "education" | "certification";
    title: string;
    organization?: string | null;
    startDate?: string | null;
    endDate?: string | null;
    location?: string | null;
    summary: string;
    bullets?: string[];
    visibility: Visibility;
    publicationStatus: "not_published" | "published";
  }>;
  evidenceLinks?: Array<{
    id: string;
    label: string;
    url: string;
    visibility: Visibility;
    publicationStatus: "not_published" | "published";
  }>;
  hasPublishedPublicContent?: boolean;
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
