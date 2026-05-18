import type { ProfileExperienceItemType, ProfileIntakeOutput, ProfileIntakeSource } from "./profile-intake-contract";

export type TargetRoleIntent = {
  targetTitles: string;
  roleFamilies: string;
  preferredWorkMode: "remote" | "hybrid" | "onsite" | "flexible";
  preferredLocations: string;
  domainsOfInterest: string;
  constraints: string;
};

export type DraftGeneratedStatus = "draft" | "needs_review";

export type DraftProfileFact = {
  id: string;
  claim: string;
  category: string;
  source: ProfileIntakeSource;
  status: DraftGeneratedStatus;
  visibility: "private";
  published: false;
};

export type DraftSkillClaim = {
  id: string;
  skill: string;
  category: string;
  evidence: string;
  yearsMin?: number;
  yearsMax?: number;
  source: ProfileIntakeSource;
  status: DraftGeneratedStatus;
  visibility: "private";
  published: false;
};

export type DraftExperienceSummary = {
  id: string;
  itemType: ProfileExperienceItemType;
  title: string;
  organization: string;
  startDate: string;
  endDate: string;
  location: string;
  summary: string;
  bullets: string[];
  source: ProfileIntakeSource;
  status: DraftGeneratedStatus;
  visibility: "private";
  published: false;
};

export type DraftEvidenceLink = {
  id: string;
  url: string;
  label: string;
  source: ProfileIntakeSource;
  status: DraftGeneratedStatus;
  visibility: "private";
  published: false;
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
  links: DraftEvidenceLink[];
  clarifyingQuestions: ClarifyingQuestion[];
};

export type MockResumeAttachment = {
  name: string;
  sizeLabel: string;
  parseStatus: "metadata_only" | "text_loaded";
};

export type MockIntakeTurnInput = {
  messageText: string;
  attachedResumeText?: string;
  currentIntent: TargetRoleIntent;
  attachment?: MockResumeAttachment | null;
};

export type MockIntakeTurn = {
  intent: TargetRoleIntent;
  draft: MockProfileDraft;
  agentMessage: string;
  changeHeadline: string;
  changeSummary: string[];
};

export const emptyTargetRoleIntent: TargetRoleIntent = {
  targetTitles: "",
  roleFamilies: "",
  preferredWorkMode: "flexible",
  preferredLocations: "",
  domainsOfInterest: "",
  constraints: ""
};

export const initialProfilePrompt = "I want to be a...";

let generatedId = 0;

function nextGeneratedId(prefix: string) {
  generatedId += 1;
  return `${prefix}-${generatedId}`;
}

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

export function createMockProfileDraft(
  resumeText: string,
  intent: TargetRoleIntent,
  source: DraftProfileFact["source"] = "resume",
  options: { includeTargetIntentFact?: boolean } = {}
): MockProfileDraft {
  const normalizedResume = resumeText.trim();
  const lowerResume = normalizedResume.toLowerCase();
  const targetSummary = summarizeTargetIntent(intent);
  const includeTargetIntentFact = options.includeTargetIntentFact ?? true;

  return {
    resumeTextLength: normalizedResume.length,
    facts: buildDraftFacts(lowerResume, targetSummary, source, includeTargetIntentFact),
    skillClaims: buildSkillClaims(lowerResume, source),
    experienceSummaries: buildExperienceSummaries(normalizedResume, source),
    links: extractLinks(normalizedResume, source),
    clarifyingQuestions: appliedAiQuestions
  };
}

export function createMockIntakeTurn(input: MockIntakeTurnInput): MockIntakeTurn {
  const messageText = input.messageText.trim();
  const attachedResumeText = input.attachedResumeText?.trim() ?? "";
  const nextIntent = mergeIntent(input.currentIntent, deriveIntentFromMessage(messageText));
  const hasAttachedResume = Boolean(attachedResumeText);
  const hasPastedResume = looksLikeResumeText(messageText);
  const hasPastWorkEvidence = looksLikePastWorkText(messageText);
  const shouldExtractProfileDraft = hasAttachedResume || hasPastedResume || hasPastWorkEvidence;
  const extractionText = [attachedResumeText, shouldExtractProfileDraft ? messageText : ""].filter(Boolean).join("\n\n");
  const source = hasAttachedResume || hasPastedResume ? "resume" : "chat";
  const draft = createMockProfileDraft(extractionText, nextIntent, source, { includeTargetIntentFact: false });
  const changeSummary = buildChangeSummary(draft, nextIntent, input.attachment);
  const changeHeadline = buildChangeHeadline(draft, Boolean(summarizeTargetIntent(nextIntent)));

  return {
    intent: nextIntent,
    draft,
    changeHeadline,
    changeSummary,
    agentMessage: shouldExtractProfileDraft
      ? "I updated the local draft from this conversation turn, kept every new claim private and marked needs review, and queued follow-up questions."
      : "I captured your target direction. Next, paste your resume into this same chat or attach it here, and I will draft profile facts for review."
  };
}

function buildDraftFacts(
  lowerResume: string,
  targetSummary: string,
  source: DraftProfileFact["source"],
  includeTargetIntentFact: boolean
): DraftProfileFact[] {
  const facts: DraftProfileFact[] = [];

  if (targetSummary && includeTargetIntentFact) {
    facts.push(createDraftFact("target-intent", `Target role intent captured: ${targetSummary}.`, "general", source));
  }

  if (mentionsAny(lowerResume, ["llm", "ai", "machine learning", "automation", "agent"])) {
    facts.push(
      createDraftFact(
        "ai-work",
        "Resume appears to mention AI, LLM, automation, machine learning, or agent-related work.",
        "ai_product",
        source
      )
    );
  }

  if (mentionsAny(lowerResume, ["python", "fastapi", "api", "backend"])) {
    facts.push(
      createDraftFact(
        "backend-work",
        "Resume appears to mention Python, API, FastAPI, or backend work.",
        "backend",
        source
      )
    );
  }

  if (mentionsAny(lowerResume, ["eval", "test", "monitor", "reliability", "observability"])) {
    facts.push(
      createDraftFact(
        "evals-reliability",
        "Resume appears to mention evals, tests, monitoring, reliability, or observability work.",
        "evals",
        source
      )
    );
  }

  if (mentionsAny(lowerResume, ["customer", "stakeholder", "client", "user", "operator"])) {
    facts.push(
      createDraftFact(
        "stakeholder-work",
        "Resume appears to mention customer, stakeholder, user, client, or operator-facing work.",
        "stakeholder_work",
        source
      )
    );
  }

  if (facts.length === 0 && lowerResume) {
    facts.push(
      createDraftFact(
        "resume-placeholder",
        "Input was provided, but this mock extractor needs a real model pass to identify specific claims.",
        "general",
        source
      )
    );
  }

  return facts;
}

function buildSkillClaims(lowerResume: string, source: DraftSkillClaim["source"]): DraftSkillClaim[] {
  const skillMap: Array<[string, string, string[]]> = [
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
      evidence: "Keyword evidence found in unverified intake text.",
      yearsMin: undefined,
      yearsMax: undefined,
      source,
      status: "needs_review",
      visibility: "private",
      published: false
    }));
}

function buildExperienceSummaries(
  resumeText: string,
  source: DraftExperienceSummary["source"]
): DraftExperienceSummary[] {
  if (!looksLikeResumeText(resumeText) && !looksLikePastWorkText(resumeText)) {
    return [];
  }

  const lines = resumeText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const likelyExperienceLine = lines.find((line) => /engineer|developer|consultant|architect|lead/i.test(line));

  if (!likelyExperienceLine) {
    return [
      {
        id: "experience-1",
        itemType: inferExperienceItemType(lines[0] || ""),
        title: lines[0]?.slice(0, 80) || "Past work item",
        organization: "Needs review",
        startDate: "",
        endDate: "",
        location: "",
        summary: "Potential past work, project, education, or artifact evidence detected from intake text.",
        bullets: [],
        source,
        status: "needs_review",
        visibility: "private",
        published: false
      }
    ];
  }

  return [
    {
      id: "experience-1",
      itemType: inferExperienceItemType(likelyExperienceLine),
      title: likelyExperienceLine.slice(0, 80),
      organization: "Needs review",
      startDate: "",
      endDate: "",
      location: "",
      summary: "Potential work, project, education, or artifact evidence detected from intake text. Candidate review is required.",
      bullets: [],
      source,
      status: "needs_review",
      visibility: "private",
      published: false
    }
  ];
}

function createDraftFact(
  id: string,
  claim: string,
  category: DraftProfileFact["category"],
  source: DraftProfileFact["source"]
): DraftProfileFact {
  return {
    id,
    claim,
    category,
    source,
    status: "needs_review",
    visibility: "private",
    published: false
  };
}

function extractLinks(resumeText: string, source: DraftEvidenceLink["source"]): DraftEvidenceLink[] {
  const matches = resumeText.match(/https?:\/\/[^\s)]+/g);
  return matches
    ? Array.from(new Set(matches)).map((url) => ({
        id: nextGeneratedId("evidence"),
        url,
        label: url,
        source,
        status: "needs_review",
        visibility: "private",
        published: false
      }))
    : [];
}

export function applyProfileIntakeOutputToState(
  currentIntent: TargetRoleIntent,
  output: ProfileIntakeOutput
): {
  draft: MockProfileDraft;
  intent: TargetRoleIntent;
  turn: MockIntakeTurn;
} {
  const intent = mergeIntent(currentIntent, {
    targetTitles: output.targetRoleIntent.targetTitles,
    roleFamilies: output.targetRoleIntent.targetRoleFamilies,
    preferredWorkMode: output.targetRoleIntent.preferredWorkMode,
    preferredLocations: output.targetRoleIntent.preferredLocations,
    domainsOfInterest: output.targetRoleIntent.domainsOrIndustries,
    constraints: output.targetRoleIntent.constraints
  });
  const draft: MockProfileDraft = {
    resumeTextLength: 0,
    facts: output.draftFacts.map((fact, index) => ({
      id: fact.id || nextGeneratedId(`fact-${index + 1}`),
      claim: fact.claim,
      category: fact.category || "general",
      source: fact.source,
      status: fact.status,
      visibility: fact.visibility,
      published: fact.published
    })),
    skillClaims: output.skillClaims.map((skill, index) => ({
      id: skill.id || nextGeneratedId(`skill-${index + 1}`),
      skill: skill.skill,
      category: skill.category || "general",
      evidence: skill.evidence || "Needs evidence review.",
      yearsMin: skill.yearsMin,
      yearsMax: skill.yearsMax,
      source: skill.source,
      status: skill.status,
      visibility: skill.visibility,
      published: skill.published
    })),
    experienceSummaries: output.experienceAndProjects.map((experience, index) => ({
      id: experience.id || nextGeneratedId(`experience-${index + 1}`),
      itemType: experience.itemType || inferExperienceItemType(`${experience.title} ${experience.summary}`),
      title: experience.title,
      organization: experience.organization || "Needs review",
      startDate: experience.startDate || "",
      endDate: experience.endDate || "",
      location: experience.location || "",
      summary: experience.summary,
      bullets: experience.bullets || [],
      source: experience.source,
      status: experience.status,
      visibility: experience.visibility,
      published: experience.published
    })),
    links: output.evidenceLinks.map((link, index) => ({
      id: link.id || nextGeneratedId(`evidence-${index + 1}`),
      url: link.url,
      label: link.label || link.url,
      source: link.source,
      status: link.status,
      visibility: link.visibility,
      published: link.published
    })),
    clarifyingQuestions: output.clarifyingQuestions.map((question, index) => ({
      id: nextGeneratedId(`question-${index + 1}`),
      topic: "Suggested next question",
      question
    }))
  };
  const changeSummary = output.changeSummary.length ? output.changeSummary : buildChangeSummary(draft, intent);

  return {
    draft,
    intent,
    turn: {
      intent,
      draft,
      agentMessage: output.assistantMessage,
      changeHeadline: buildChangeHeadline(draft, Boolean(summarizeTargetIntent(intent))),
      changeSummary
    }
  };
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

function deriveIntentFromMessage(messageText: string): Partial<TargetRoleIntent> {
  const normalized = messageText.trim();
  const lower = normalized.toLowerCase();
  const intent: Partial<TargetRoleIntent> = {};
  const targetMatch = normalized.match(/i want to be an?\s+(.+)/i);

  if (targetMatch?.[1]) {
    intent.targetTitles = targetMatch[1].replace(/[.!?]+$/, "").trim();
  }

  if (mentionsAny(lower, ["llm", "agent", "ai", "machine learning", "eval", "retrieval", "rag"])) {
    intent.roleFamilies = "Applied AI, LLM systems, evals, and agentic workflows";
  }

  if (mentionsAny(lower, ["remote"])) {
    intent.preferredWorkMode = "remote";
  } else if (mentionsAny(lower, ["hybrid"])) {
    intent.preferredWorkMode = "hybrid";
  } else if (mentionsAny(lower, ["onsite", "on-site"])) {
    intent.preferredWorkMode = "onsite";
  }

  if (mentionsAny(lower, ["healthcare", "education", "developer tools", "enterprise", "finance"])) {
    intent.domainsOfInterest = [
      lower.includes("developer tools") ? "developer tools" : "",
      lower.includes("education") ? "education" : "",
      lower.includes("healthcare") ? "healthcare" : "",
      lower.includes("enterprise") ? "enterprise AI" : "",
      lower.includes("finance") ? "finance" : ""
    ]
      .filter(Boolean)
      .join(", ");
  }

  return intent;
}

function mergeIntent(currentIntent: TargetRoleIntent, derivedIntent: Partial<TargetRoleIntent>): TargetRoleIntent {
  return {
    ...currentIntent,
    ...Object.fromEntries(
      Object.entries(derivedIntent).filter(([, value]) => typeof value === "string" && value.trim().length > 0)
    )
  };
}

function buildChangeSummary(
  draft: MockProfileDraft,
  intent: TargetRoleIntent,
  attachment?: MockResumeAttachment | null
): string[] {
  const summary = [
    summarizeTargetIntent(intent)
      ? `Updated target role intent: ${summarizeTargetIntent(intent)}.`
      : "Target role intent still needs more detail.",
    `Created ${draft.facts.length} draft claim(s), ${draft.skillClaims.length} skill claim(s), and ${draft.experienceSummaries.length} experience/project item(s).`,
    "Kept all generated data private, unpublished, and marked needs review.",
    `Queued ${draft.clarifyingQuestions.length} clarifying question(s) for applied AI and FDE positioning.`
  ];

  if (attachment) {
    summary.push(`Recorded resume attachment metadata for ${attachment.name}; ${attachment.parseStatus}.`);
  }

  return summary;
}

function buildChangeHeadline(draft: MockProfileDraft, hasTargetIntent: boolean): string {
  const intentSummary = hasTargetIntent ? "Updated target role intent." : "Target role intent still needs detail.";

  return `${intentSummary} Created ${draft.facts.length} draft claim(s). Added ${draft.clarifyingQuestions.length} follow-up question(s).`;
}

function mentionsAny(text: string, keywords: string[]): boolean {
  return keywords.some((keyword) => text.includes(keyword));
}

function looksLikeResumeText(text: string): boolean {
  const normalized = text.trim().toLowerCase();
  const lines = normalized.split(/\r?\n/).filter(Boolean);
  const resumeSignals = [
    "experience",
    "education",
    "skills",
    "projects",
    "work history",
    "employment",
    "certifications",
    "github",
    "linkedin"
  ];

  return lines.length >= 3 || mentionsAny(normalized, resumeSignals);
}

function looksLikePastWorkText(text: string): boolean {
  const normalized = text.trim().toLowerCase();
  const pastWorkSignals = [
    "i built",
    "i shipped",
    "i led",
    "i created",
    "i developed",
    "i implemented",
    "i launched",
    "i maintained",
    "i worked",
    "built a",
    "built an",
    "shipped a",
    "shipped an",
    "led a",
    "created a",
    "developed a",
    "implemented a",
    "project:",
    "open source",
    "publication",
    "certification",
    "at "
  ];

  return mentionsAny(normalized, pastWorkSignals);
}

function inferExperienceItemType(text: string): ProfileExperienceItemType {
  const normalized = text.toLowerCase();
  if (mentionsAny(normalized, ["certificate", "certification", "coursera"])) {
    return "certification";
  }
  if (mentionsAny(normalized, ["education", "university", "college", "b.a.", "b.s.", "degree"])) {
    return "education";
  }
  if (mentionsAny(normalized, ["project", "platform", "console", "dashboard", "knowledge base"])) {
    return "project";
  }
  return "experience";
}
