from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import Base, EvidenceArtifact, ExperienceProjectDraft, ProfileFact, ProfileFieldValue, SkillClaim
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.main import app
from jobops_api.model_connector import ModelConnector, ModelConnectorConfig, ModelRequest, ModelResponse
from jobops_api.model_connector.routing import ModelRoutingConfig
from jobops_api.profiles import candidate_profile_to_public_dict
from jobops_api.public_candidate_agent import (
    answer_public_candidate_question,
    build_public_candidate_context,
)
from jobops_api.settings import Settings


def test_public_profile_context_exposes_only_public_published_items() -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = seed_public_items(session)
        public_profile = candidate_profile_to_public_dict(profile)
        context = build_public_candidate_context(public_profile)

    context_text = json.dumps(context)
    assert "Published public fact." in context_text
    assert "Public profile headline." in context_text
    assert "Applied AI" in context_text
    assert "Public Python evidence." in context_text
    assert "Published project summary." in context_text
    assert "https://example.com/public" in context_text
    assert "Private draft fact." not in context_text
    assert "Candidate approved unpublished fact." not in context_text
    assert "Private Python evidence." not in context_text
    assert "Private mailing address." not in context_text
    assert "Private compensation floor." not in context_text
    assert "Draft project summary." not in context_text
    assert "https://example.com/private" not in context_text


def test_public_candidate_question_endpoint_is_public_and_uses_only_public_context(monkeypatch) -> None:
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_seeded_engine()

    with Session(engine) as session:
        seed_public_items(session)
        session.commit()

    with app_with_session(engine):
        response = TestClient(app).post(
            "/v1/public/portfolio/rebekah-love/questions",
            json={"question": "What public project has Rebekah built?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "Published project summary." in payload["answer"]
    assert "Private draft fact." not in payload["answer"]
    assert payload["verifiedFactsUsed"]


def test_public_candidate_question_endpoint_returns_unknown_without_support(monkeypatch) -> None:
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_seeded_engine()

    with Session(engine) as session:
        seed_public_items(session)
        session.commit()

    with app_with_session(engine):
        response = TestClient(app).post(
            "/v1/public/portfolio/rebekah-love/questions",
            json={"question": "What compensation package is Rebekah seeking?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "The published public profile does not include that information."
    assert payload["verifiedFactsUsed"] == []
    assert "No supplied published public fact supports" in payload["unknowns"][0]


def test_public_candidate_question_model_request_excludes_private_data(monkeypatch) -> None:
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_seeded_engine()
    connector = RecordingConnector()

    with Session(engine) as session:
        profile = seed_public_items(session)
        public_profile = candidate_profile_to_public_dict(profile)
        result = answer_public_candidate_question(
            public_profile=public_profile,
            question="What public fact is available?",
            settings=make_test_settings(),
            connector=connector,
        )

    assert result.status_code == 200
    assert connector.request is not None
    request_text = "\n".join(message.content for message in connector.request.messages)
    assert "Published public fact." in request_text
    assert "Private draft fact." not in request_text
    assert "Candidate approved unpublished fact." not in request_text
    assert "Private Python evidence." not in request_text


def create_seeded_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def seed_public_items(session: Session):
    profile = seed_public_profile(
        session,
        {
            "slug": "rebekah-love",
            "displayName": "Rebekah Love",
            "headline": "Applied AI engineer",
            "summary": "Public summary.",
            "profileStatus": "published",
        },
        hostname="rebekahalove.dev",
    )
    session.add_all(
        [
            ProfileFact(
                candidate_profile_id=profile.id,
                fact_type="impact",
                claim="Published public fact.",
                structured_value={},
                source="resume",
                visibility="public",
                verification_status="published",
            ),
            ProfileFact(
                candidate_profile_id=profile.id,
                fact_type="private",
                claim="Private draft fact.",
                structured_value={},
                source="resume",
                visibility="private",
                verification_status="draft",
            ),
            ProfileFact(
                candidate_profile_id=profile.id,
                fact_type="unpublished",
                claim="Candidate approved unpublished fact.",
                structured_value={},
                source="resume",
                visibility="public",
                verification_status="candidate_approved",
            ),
            SkillClaim(
                candidate_profile_id=profile.id,
                skill_name="Python",
                skill_category="engineering",
                evidence_summary="Public Python evidence.",
                visibility="public",
                verification_status="published",
                publication_status="published",
            ),
            SkillClaim(
                candidate_profile_id=profile.id,
                skill_name="Private skill",
                skill_category="private",
                evidence_summary="Private Python evidence.",
                visibility="private",
                verification_status="published",
                publication_status="published",
            ),
            ExperienceProjectDraft(
                candidate_profile_id=profile.id,
                title="Public Project",
                organization="Public Org",
                summary="Published project summary.",
                visibility="public",
                publication_status="published",
            ),
            ExperienceProjectDraft(
                candidate_profile_id=profile.id,
                title="Private Project",
                organization="Private Org",
                summary="Draft project summary.",
                visibility="public",
                publication_status="not_published",
            ),
            EvidenceArtifact(
                candidate_profile_id=profile.id,
                artifact_type="url",
                label="Public URL",
                uri="https://example.com/public",
                visibility="public",
                publication_status="published",
            ),
            EvidenceArtifact(
                candidate_profile_id=profile.id,
                artifact_type="url",
                label="Private URL",
                uri="https://example.com/private",
                visibility="private",
                publication_status="published",
            ),
            ProfileFieldValue(
                candidate_profile_id=profile.id,
                field_group="profile_basics",
                field_name="headline",
                value_text="Public profile headline.",
                source="user",
                lifecycle_status="published",
                visibility="public",
            ),
            ProfileFieldValue(
                candidate_profile_id=profile.id,
                field_group="profile_basics",
                field_name="mailingAddress",
                value_text="Private mailing address.",
                source="user",
                lifecycle_status="published",
                visibility="private",
            ),
            ProfileFieldValue(
                candidate_profile_id=profile.id,
                field_group="targets",
                field_name="roleFamilies",
                value_text="Applied AI",
                source="user",
                lifecycle_status="published",
                visibility="public",
            ),
            ProfileFieldValue(
                candidate_profile_id=profile.id,
                field_group="targets",
                field_name="compensationMin",
                value_text="Private compensation floor.",
                source="user",
                lifecycle_status="published",
                visibility="private",
            ),
        ]
    )
    session.flush()
    return profile


class RecordingProvider:
    request: ModelRequest | None = None

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.request = request
        return ModelResponse(
            text=json.dumps(
                {
                    "answer": "The published public profile says: Published public fact.",
                    "verifiedFactsUsed": [],
                    "inferences": [],
                    "unknowns": [],
                    "caveats": [],
                }
            ),
            provider="recording",
            model=request.model or "recording",
        )


class RecordingConnector(ModelConnector):
    def __init__(self) -> None:
        self.provider = RecordingProvider()
        super().__init__(
            self.provider,
            ModelConnectorConfig(
                provider="mock",
                routing=ModelRoutingConfig(default_model="mock-default", cheap_model="mock-cheap"),
            ),
        )

    @property
    def request(self) -> ModelRequest | None:
        return self.provider.request


class app_with_session:
    def __init__(self, engine) -> None:
        self.engine = engine

    def __enter__(self):
        def override_session() -> Iterator[Session]:
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db_session] = override_session
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        app.dependency_overrides.clear()


def make_test_settings() -> Settings:
    return Settings(
        app_env="test",
        model_provider="mock",
        default_model="mock-default",
        cheap_model="mock-cheap",
        gemini_api_key=None,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        company_discovery_search_grounding_enabled=False,
        database_url=None,
        repo_root=Path("."),
    )
