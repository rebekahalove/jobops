export type TargetRoleIntent = {
  targetTitles: string;
  roleFamilies: string;
  preferredWorkMode: "remote" | "hybrid" | "onsite" | "flexible";
  preferredLocations: string;
  domainsOfInterest: string;
  constraints: string;
};

export type DraftProfileFact = {
  id: string;
  claim: string;
  category: "ai_product" | "backend" | "evals" | "stakeholder_work" | "general";
  source: "resume_derived";
  reviewStatus: "draft";
  verificationStatus: "not_verified";
  visibility: "private";
};

export type DraftSkillClaim = {
  id: string;
  skill: string;
  category: "programming" | "ai_systems" | "backend" | "data" | "delivery";
  evidence: string;
  source: "resume_derived";
  verificationStatus: "not_verified";
};

export type DraftExperienceSummary = {
  id: string;
  title: string;
  organization: string;
  summary: string;
  source: "resume_derived";
  verificationStatus: "not_verified";
};

export type ClarifyingQuestion = {
  id: string;
  topic: string;
  question: string;
};

export type MockProfileDraft = {
  resumeTextLength: number;
  facts: DraftProfileFact[];
  skillClaims: DraftSkillClaim[];
  experienceSummaries: DraftExperienceSummary[];
  links: string[];
  clarifyingQuestions: ClarifyingQuestion[];
};

export const emptyTargetRoleIntent: TargetRoleIntent = {
  targetTitles: "",
  roleFamilies: "",
  preferredWorkMode: "flexible",
  preferredLocations: "",
  domainsOfInterest: "",
  constraints: ""
};

const appliedAiQuestions: ClarifyingQuestion[] = [
  {
    id: "q-ai-products",
    topic: "Shipped AI products",
    question: "What AI, automation, or agentic products have you shipped beyond a prototype?"
  },
  {
    id: "q-evals",
    topic: "Evals and reliability",
    question: "Have you built evals, regression tests, monitoring, or reliability checks for model behavior?"
  },
  {
    id: "q-production",
    topic: "Production constraints",
    question: "Which production constraints did you handle: latency, cost, safety, observability, or failure recovery?"
  },
  {
    id: "q-outcomes",
    topic: "Measurable outcomes",
    question: "What outcomes can we quantify for your strongest projects or roles?"
  },
  {
    id: "q-stakeholders",
    topic: "Stakeholder work",
    question: "Where have you worked directly with users, customers, operators, or business stakeholders?"
  },
  {
    id: "q-artifacts",
    topic: "Public artifacts",
    question: "Which repos, demos, case studies, writing, or talks can support these claims publicly?"
  }
];

export function createMockProfileDraft(resumeText: string, intent: TargetRoleIntent): MockProfileDraft {
  const normalizedResume = resumeText.trim();
  const lowerResume = normalizedResume.toLowerCase();
  const targetSummary = summarizeTargetIntent(intent);

  return {
    resumeTextLength: normalizedResume.length,
    facts: buildDraftFacts(lowerResume, targetSummary),
    skillClaims: buildSkillClaims(lowerResume),
    experienceSummaries: buildExperienceSummaries(normalizedResume),
    links: extractLinks(normalizedResume),
    clarifyingQuestions: appliedAiQuestions
  };
}

function buildDraftFacts(lowerResume: string, targetSummary: string): DraftProfileFact[] {
  const facts: DraftProfileFact[] = [];

  if (targetSummary) {
    facts.push(createDraftFact("target-intent", `Target role intent captured: ${targetSummary}.`, "general"));
  }

  if (mentionsAny(lowerResume, ["llm", "ai", "machine learning", "automation", "agent"])) {
    facts.push(
      createDraftFact(
        "ai-work",
        "Resume appears to mention AI, LLM, automation, machine learning, or agent-related work.",
        "ai_product"
      )
    );
  }

  if (mentionsAny(lowerResume, ["python", "fastapi", "api", "backend"])) {
    facts.push(
      createDraftFact("backend-work", "Resume appears to mention Python, API, FastAPI, or backend work.", "backend")
    );
  }

  if (mentionsAny(lowerResume, ["eval", "test", "monitor", "reliability", "observability"])) {
    facts.push(
      createDraftFact(
        "evals-reliability",
        "Resume appears to mention evals, tests, monitoring, reliability, or observability work.",
        "evals"
      )
    );
  }

  if (mentionsAny(lowerResume, ["customer", "stakeholder", "client", "user", "operator"])) {
    facts.push(
      createDraftFact(
        "stakeholder-work",
        "Resume appears to mention customer, stakeholder, user, client, or operator-facing work.",
        "stakeholder_work"
      )
    );
  }

  if (facts.length === 0) {
    facts.push(
      createDraftFact(
        "resume-placeholder",
        "Resume text was provided, but this mock extractor needs a real model pass to identify specific claims.",
        "general"
      )
    );
  }

  return facts;
}

function buildSkillClaims(lowerResume: string): DraftSkillClaim[] {
  const skillMap: Array<[string, DraftSkillClaim["category"], string[]]> = [
    ["Python", "programming", ["python"]],
    ["TypeScript", "programming", ["typescript", "javascript", "react", "next.js", "nextjs"]],
    ["LLM systems", "ai_systems", ["llm", "prompt", "agent", "rag", "retrieval"]],
    ["Backend APIs", "backend", ["api", "fastapi", "backend", "server"]],
    ["Postgres", "data", ["postgres", "postgresql", "sql"]],
    ["Applied delivery", "delivery", ["customer", "stakeholder", "client", "user"]]
  ];

  return skillMap
    .filter(([, , keywords]) => mentionsAny(lowerResume, keywords))
    .map(([skill, category], index) => ({
      id: `skill-${index + 1}`,
      skill,
      category,
      evidence: "Keyword evidence found in pasted resume text.",
      source: "resume_derived",
      verificationStatus: "not_verified"
    }));
}

function buildExperienceSummaries(resumeText: string): DraftExperienceSummary[] {
  const lines = resumeText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const likelyExperienceLine = lines.find((line) => /engineer|developer|consultant|architect|lead/i.test(line));

  if (!likelyExperienceLine) {
    return [
      {
        id: "experience-1",
        title: "Experience summary pending",
        organization: "Unknown",
        summary: "The mock extractor did not identify a clear role line. A model-backed extractor should draft this later.",
        source: "resume_derived",
        verificationStatus: "not_verified"
      }
    ];
  }

  return [
    {
      id: "experience-1",
      title: likelyExperienceLine.slice(0, 80),
      organization: "Needs review",
      summary: "Potential experience entry detected from pasted resume text. Candidate review is required.",
      source: "resume_derived",
      verificationStatus: "not_verified"
    }
  ];
}

function createDraftFact(
  id: string,
  claim: string,
  category: DraftProfileFact["category"]
): DraftProfileFact {
  return {
    id,
    claim,
    category,
    source: "resume_derived",
    reviewStatus: "draft",
    verificationStatus: "not_verified",
    visibility: "private"
  };
}

function extractLinks(resumeText: string): string[] {
  const matches = resumeText.match(/https?:\/\/[^\s)]+/g);
  return matches ? Array.from(new Set(matches)) : [];
}

function summarizeTargetIntent(intent: TargetRoleIntent): string {
  return [
    intent.targetTitles,
    intent.roleFamilies,
    intent.preferredWorkMode,
    intent.preferredLocations,
    intent.domainsOfInterest,
    intent.constraints
  ]
    .map((value) => value.trim())
    .filter(Boolean)
    .join(" | ");
}

function mentionsAny(text: string, keywords: string[]): boolean {
  return keywords.some((keyword) => text.includes(keyword));
}
