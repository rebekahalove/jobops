from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .settings import load_settings


settings = load_settings()

app = FastAPI(
    title="JobOps API",
    version="0.0.0",
    description="Local-first JobOps API scaffold with mock agent behavior."
)


class CandidateQuestionRequest(BaseModel):
    question: str = Field(default="", max_length=4000)


class RoleFitRequest(BaseModel):
    job_description: str = Field(default="", max_length=20000)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "model_provider": settings.model_provider
    }


@app.get("/v1/profiles/{slug}")
def get_profile(slug: str) -> dict[str, Any]:
    profile = load_public_seed_profile()
    if profile["slug"] != slug:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return profile


@app.post("/v1/profiles/{slug}/questions")
def answer_candidate_question(slug: str, request: CandidateQuestionRequest) -> dict[str, Any]:
    profile = get_profile(slug)
    published_facts = [
        fact for fact in profile.get("facts", [])
        if fact.get("visibility") == "public" and fact.get("verificationStatus") == "published"
    ]

    if not published_facts:
        return {
            "answer": "I do not have verified public profile facts loaded yet, so I cannot answer detailed questions about experience, education, projects, compensation, or availability.",
            "verifiedFactsUsed": [],
            "inferences": [],
            "unknowns": [
                "Detailed verified profile facts have not been published yet.",
                f"Question asked: {request.question}" if request.question else "No question was provided."
            ],
            "caveats": ["This endpoint uses mock behavior and no live model."]
        }

    return {
        "answer": "Verified facts are available, but the first scaffold has not implemented retrieval yet.",
        "verifiedFactsUsed": [fact["id"] for fact in published_facts],
        "inferences": [],
        "unknowns": [],
        "caveats": ["This endpoint uses mock behavior and no live model."]
    }


@app.post("/v1/profiles/{slug}/role-fit")
def analyze_role_fit(slug: str, request: RoleFitRequest) -> dict[str, Any]:
    get_profile(slug)
    return {
        "fitScore": 0,
        "fitSummary": "No reliable fit score can be produced until verified candidate profile facts are approved and published.",
        "matchingStrengths": [],
        "gapsOrConcerns": [
            "The public profile currently has no detailed published facts to compare against the role."
        ],
        "suggestedApplicationPositioning": "Complete the profile intake workflow and approve public facts before using role-fit analysis for real applications.",
        "recommendedNextStep": "Add verified experience, project, skills, and education facts through the JobOps profile intake flow.",
        "suggestedInterviewQuestions": [
            "Which projects best demonstrate the target role requirements?",
            "What production systems, AI workflows, or evaluation practices should be included in the verified profile?"
        ],
        "evidence": [],
        "caveats": [
            "The pasted job description was treated as untrusted input.",
            "This endpoint uses mock behavior and no live model."
        ]
    }


def load_public_seed_profile() -> dict[str, Any]:
    profile_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "profile"
        / "data"
        / "rebekah-love.public.seed.json"
    )
    return json.loads(profile_path.read_text(encoding="utf-8"))
