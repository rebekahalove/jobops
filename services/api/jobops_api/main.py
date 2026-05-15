from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .applications import router as applications_router
from .command_center import router as command_center_router
from .db.session import get_db_session
from .profile_intake import ProfileIntakeExtractRequest, run_profile_intake_extraction
from .profiles import candidate_profile_to_public_dict, get_candidate_profile_by_hostname, get_candidate_profile_by_slug
from .security import INTERNAL_API_KEY_HEADER, require_internal_api_key
from .settings import load_settings


settings = load_settings()


def configure_cors(api_app: FastAPI, *, allowed_origins: tuple[str, ...]) -> None:
    if not allowed_origins:
        return

    api_app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", INTERNAL_API_KEY_HEADER],
    )


app = FastAPI(
    title="JobOps API",
    version="0.0.0",
    description="Local-first JobOps API scaffold with mock agent behavior.",
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)

configure_cors(app, allowed_origins=settings.cors_origins)
app.include_router(applications_router)
app.include_router(command_center_router)


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
def get_profile(slug: str, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    candidate_profile = get_profile_or_404(session, slug)
    return candidate_profile_to_public_dict(candidate_profile)


@app.get("/v1/profile-by-hostname/{hostname}")
def get_profile_by_hostname(hostname: str, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    candidate_profile = get_candidate_profile_by_hostname(session, hostname)
    if candidate_profile is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return candidate_profile_to_public_dict(candidate_profile)


@app.post("/v1/profile-intake/extract", dependencies=[Depends(require_internal_api_key)])
def extract_profile_intake(
    request: ProfileIntakeExtractRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    result = run_profile_intake_extraction(request, db_session=session, settings=settings)
    return JSONResponse(content=result.body, status_code=result.status_code)


@app.post("/v1/profiles/{slug}/questions", dependencies=[Depends(require_internal_api_key)])
def answer_candidate_question(
    slug: str,
    request: CandidateQuestionRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    profile = candidate_profile_to_public_dict(get_profile_or_404(session, slug))
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


@app.post("/v1/profiles/{slug}/role-fit", dependencies=[Depends(require_internal_api_key)])
def analyze_role_fit(
    slug: str,
    request: RoleFitRequest,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    get_profile_or_404(session, slug)
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


def get_profile_or_404(session: Session, slug: str):
    candidate_profile = get_candidate_profile_by_slug(session, slug)
    if candidate_profile is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return candidate_profile
