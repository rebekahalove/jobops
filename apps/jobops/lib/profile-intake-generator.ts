import {
  createModelConnector,
  generateStructuredOutput,
  MockModelConnector,
  type ModelConnector,
  type ModelConnectorConfig,
  type ModelRequest
} from "@jobops/model-connector/server";
import { createDefaultRoutingConfig } from "@jobops/model-connector";
import {
  profileIntakeJsonSchema,
  type ProfileIntakeApiRequest,
  type ProfileIntakeOutput,
  validateProfileIntakeOutput
} from "./profile-intake-contract";
import { buildProfileIntakeUserPrompt, profileIntakeSystemPrompt } from "./profile-intake-prompt";

export async function generateProfileIntakeOutput(
  connector: ModelConnector,
  input: ProfileIntakeApiRequest
): Promise<ProfileIntakeOutput> {
  const request: ModelRequest = {
    task: "profile_extract",
    temperature: 0,
    maxOutputTokens: 4000,
    responseFormat: {
      type: "json",
      schemaName: "jobops_profile_intake",
      schema: profileIntakeJsonSchema
    },
    messages: [
      {
        role: "system",
        content: profileIntakeSystemPrompt
      },
      {
        role: "user",
        content: buildProfileIntakeUserPrompt(input)
      }
    ],
    metadata: {
      feature: "profile_intake_shell"
    }
  };

  const response = await generateStructuredOutput(connector, request, validateProfileIntakeOutput);
  return response.value;
}

export function createProfileIntakeConnector(config: ModelConnectorConfig): ModelConnector {
  if (config.provider === "mock") {
    return new MockModelConnector({
      ...createDefaultRoutingConfig(config),
      responsesByTask: {
        profile_extract: (request) => buildMockProfileIntakeResponse(request)
      }
    });
  }

  return createModelConnector(config);
}

function buildMockProfileIntakeResponse(request: ModelRequest) {
  const message = extractLatestUserMessage(request);
  const lower = message.toLowerCase();
  const isResumeLike = looksLikeResumeOrWorkHistory(message);
  const isPastWorkLike = looksLikePastWork(message);
  const shouldExtractProfileItems = isResumeLike || isPastWorkLike;
  const source = isResumeLike ? "resume" : isPastWorkLike ? "chat" : "model";
  const title = extractTargetTitle(message);
  const mentionsAi = mentionsAny(lower, ["ai", "llm", "agent", "automation", "machine learning", "rag", "eval"]);
  const mentionsBackend = mentionsAny(lower, ["python", "fastapi", "api", "backend", "typescript", "postgres"]);
  const mentionsReliability = mentionsAny(lower, ["eval", "test", "monitor", "observability", "reliability"]);
  const links = Array.from(new Set(message.match(/https?:\/\/[^\s)]+/g) ?? []));

  const draftFacts = shouldExtractProfileItems
    ? [
        ...(mentionsAi
          ? [
              generatedItem({
                claim: "Intake text appears to mention AI, LLM, automation, agentic, or machine-learning work.",
                category: "applied_ai",
                source
              })
            ]
          : []),
        ...(mentionsBackend
          ? [
              generatedItem({
                claim: "Intake text appears to mention backend, API, Python, TypeScript, Postgres, or FastAPI work.",
                category: "engineering",
                source
              })
            ]
          : []),
        ...(mentionsReliability
          ? [
              generatedItem({
                claim: "Intake text appears to mention evals, tests, monitoring, observability, or reliability work.",
                category: "reliability",
                source
              })
            ]
          : [])
      ]
    : [];

  const skillClaims = shouldExtractProfileItems
    ? [
        ...skillIf(lower, "Python", "programming", ["python"], source),
        ...skillIf(lower, "FastAPI", "backend", ["fastapi"], source),
        ...skillIf(lower, "LLM systems", "ai_systems", ["llm", "agent", "rag", "prompt"], source),
        ...skillIf(lower, "Evals and reliability", "quality", ["eval", "monitor", "observability", "test"], source),
        ...skillIf(lower, "Postgres", "data", ["postgres", "postgresql", "sql"], source)
      ]
    : [];

  const experienceAndProjects = shouldExtractProfileItems
    ? [
        generatedItem({
          title: firstInterestingLine(message) || "Experience or project draft",
          organization: "Needs review",
          summary: "Potential work, project, education, or artifact evidence detected from intake text.",
          source
        })
      ]
    : [];

  return JSON.stringify({
    assistantMessage:
      draftFacts.length || skillClaims.length || experienceAndProjects.length
        ? "I drafted profile updates from your message. Everything is still private and needs your review. Next, tell me about measurable outcomes or production constraints for the strongest example."
        : "I captured your target direction. Next, paste your resume or describe a shipped project so I can draft evidence-backed profile items.",
    targetRoleIntent: {
      ...(title ? { targetTitles: title } : {}),
      ...(mentionsAi ? { targetRoleFamilies: "Applied AI, LLM systems, and forward-deployed engineering" } : {}),
      ...(lower.includes("remote") ? { preferredWorkMode: "remote" } : {}),
      ...(lower.includes("hybrid") ? { preferredWorkMode: "hybrid" } : {}),
      ...(lower.includes("developer tools") ? { domainsOrIndustries: "developer tools" } : {})
    },
    draftFacts,
    skillClaims,
    experienceAndProjects,
    evidenceLinks: links.map((url) => generatedItem({ url, label: url, source })),
    clarifyingQuestions: [
      "What AI, automation, or agentic products have you shipped beyond a prototype?",
      "Which production constraints did you handle: latency, cost, safety, observability, or failure recovery?",
      "What measurable outcome can we attach to your strongest example?"
    ],
    changeSummary: [
      title ? "Updated target role intent." : "Target role intent still needs detail.",
      `Created ${draftFacts.length} draft claim(s), ${skillClaims.length} skill claim(s), and ${experienceAndProjects.length} experience/project item(s).`,
      "Kept all generated data private, unpublished, and marked for review."
    ]
  });
}

function generatedItem<T extends Record<string, unknown>>(item: T): T & {
  status: "needs_review";
  visibility: "private";
  published: false;
} {
  return {
    ...item,
    status: "needs_review",
    visibility: "private",
    published: false
  };
}

function extractLatestUserMessage(request: ModelRequest) {
  const rawContent = findLastUserMessage(request)?.content ?? "";
  try {
    const parsed = JSON.parse(rawContent) as { latestUserMessage?: unknown };
    return typeof parsed.latestUserMessage === "string" ? parsed.latestUserMessage : rawContent;
  } catch {
    return rawContent;
  }
}

function findLastUserMessage(request: ModelRequest) {
  for (let index = request.messages.length - 1; index >= 0; index -= 1) {
    const message = request.messages[index];
    if (message.role === "user") {
      return message;
    }
  }

  return undefined;
}

function extractTargetTitle(message: string) {
  return message.match(/i want to be an?\s+([^.\n]+)/i)?.[1]?.trim();
}

function firstInterestingLine(message: string) {
  return message
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => /engineer|developer|consultant|architect|lead|project|education|certification/i.test(line))
    ?.slice(0, 90);
}

function skillIf(
  lowerText: string,
  skill: string,
  category: string,
  keywords: string[],
  source: "chat" | "resume" | "model"
) {
  if (!mentionsAny(lowerText, keywords)) {
    return [];
  }

  return [
    generatedItem({
      skill,
      category,
      evidence: "Keyword evidence found in unverified intake text.",
      source
    })
  ];
}

function looksLikeResumeOrWorkHistory(message: string) {
  const lower = message.toLowerCase();
  const lines = message.split(/\r?\n/).filter((line) => line.trim());
  return (
    lines.length >= 3 ||
    mentionsAny(lower, [
      "experience",
      "education",
      "skills",
      "projects",
      "certification",
      "github",
      "linkedin",
      "work history"
    ])
  );
}

function looksLikePastWork(message: string) {
  return mentionsAny(message.toLowerCase(), [
    "i built",
    "i shipped",
    "i led",
    "i created",
    "i developed",
    "i implemented",
    "built a",
    "built an",
    "shipped a",
    "project:",
    "open source",
    "publication",
    "certification"
  ]);
}

function mentionsAny(text: string, keywords: string[]) {
  return keywords.some((keyword) => text.includes(keyword));
}
