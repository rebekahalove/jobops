import { NextResponse } from "next/server";
import type { CandidateAnswer } from "@jobops/contracts";
import { getServerEnvValue } from "../../../../lib/server-env";

const SAFE_FALLBACK: CandidateAnswer = {
  answer: "The public candidate agent is temporarily unavailable. Please try again later.",
  verifiedFactsUsed: [],
  inferences: [],
  unknowns: [],
  caveats: ["Answered only from published public profile information."]
};

export async function POST(request: Request) {
  const body = await readJson(request);
  const profileSlug = typeof body.profileSlug === "string" ? body.profileSlug.trim() : "";
  const question = typeof body.question === "string" ? body.question.trim() : "";

  if (!profileSlug || !question) {
    return NextResponse.json(
      {
        ...SAFE_FALLBACK,
        answer: "Ask a question about the published public profile to use the candidate agent.",
        unknowns: ["A profile slug and question are required."]
      },
      { status: 400 }
    );
  }

  const apiBaseUrl = await getServerEnvValue("JOBOPS_API_BASE_URL");
  if (!apiBaseUrl) {
    console.error("[JobOps portfolio] Public candidate-agent API base URL is not configured.");
    return NextResponse.json(SAFE_FALLBACK);
  }

  try {
    const response = await fetch(
      `${apiBaseUrl.replace(/\/$/, "")}/v1/public/portfolio/${encodeURIComponent(profileSlug)}/questions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        cache: "no-store"
      }
    );

    if (!response.ok) {
      console.error("[JobOps portfolio] Public candidate-agent backend returned an error.", {
        status: response.status
      });
      return NextResponse.json(SAFE_FALLBACK);
    }

    return NextResponse.json(sanitizeAnswer(await response.json()));
  } catch (error) {
    console.error("[JobOps portfolio] Public candidate-agent backend request failed.", error);
    return NextResponse.json(SAFE_FALLBACK);
  }
}

async function readJson(request: Request): Promise<Record<string, unknown>> {
  try {
    const value = await request.json();
    return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function sanitizeAnswer(value: unknown): CandidateAnswer {
  if (!value || typeof value !== "object") {
    return SAFE_FALLBACK;
  }

  const record = value as Record<string, unknown>;
  return {
    answer: stringValue(record.answer) || SAFE_FALLBACK.answer,
    verifiedFactsUsed: stringList(record.verifiedFactsUsed),
    inferences: stringList(record.inferences),
    unknowns: stringList(record.unknowns),
    caveats: stringList(record.caveats)
  };
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim().slice(0, 3000) : "";
}

function stringList(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean).slice(0, 12)
    : [];
}
