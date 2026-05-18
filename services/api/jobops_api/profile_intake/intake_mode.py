from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ProfileIntakeMode = Literal["chat_update", "resume_intake"]


@dataclass(frozen=True)
class IntakeCapacity:
    draft_facts: int
    skill_claims: int
    experience_and_projects: int
    evidence_links: int
    clarifying_questions: int
    change_summary: int

    def to_json(self) -> dict[str, int]:
        return {
            "draftFacts": self.draft_facts,
            "skillClaims": self.skill_claims,
            "experienceAndProjects": self.experience_and_projects,
            "evidenceLinks": self.evidence_links,
            "clarifyingQuestions": self.clarifying_questions,
            "changeSummary": self.change_summary,
        }


CHAT_UPDATE_CAPACITY = IntakeCapacity(
    draft_facts=4,
    skill_claims=6,
    experience_and_projects=3,
    evidence_links=4,
    clarifying_questions=3,
    change_summary=3,
)

RESUME_INTAKE_CAPACITY = IntakeCapacity(
    draft_facts=32,
    skill_claims=50,
    experience_and_projects=18,
    evidence_links=20,
    clarifying_questions=6,
    change_summary=12,
)

CHAT_UPDATE_MAX_OUTPUT_TOKENS = 5000
RESUME_INTAKE_MAX_OUTPUT_TOKENS = 16000

SECTION_HEADING_PATTERN = re.compile(
    r"(?im)^\s*(experience|work history|employment|education|skills|technical skills|projects|"
    r"certifications|certificates|publications|open source|summary)\s*:?\s*$"
)
DATE_RANGE_PATTERN = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|\d{4})"
    r"[\w\s,./-]{0,24}(?:-|to|through|present|current)[\w\s,./-]{0,24}(?:\d{4}|present|current)\b"
)
ROLE_PATTERN = re.compile(
    r"(?i)\b(engineer|developer|architect|manager|director|analyst|consultant|lead|founder|"
    r"intern|specialist|designer|scientist|administrator)\b"
)
EXPLICIT_RESUME_PATTERN = re.compile(r"(?i)\b(resume|cv)\b")


def detect_profile_intake_mode(latest_user_message: str) -> ProfileIntakeMode:
    text = latest_user_message.strip()
    lower = text.casefold()
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    section_count = len(SECTION_HEADING_PATTERN.findall(text))
    date_range_count = len(DATE_RANGE_PATTERN.findall(text))
    role_line_count = sum(1 for line in non_empty_lines if ROLE_PATTERN.search(line))

    if EXPLICIT_RESUME_PATTERN.search(lower):
        return "resume_intake"
    if len(text) >= 2500 and section_count >= 2:
        return "resume_intake"
    if len(non_empty_lines) >= 16 and section_count >= 2:
        return "resume_intake"
    if section_count >= 3:
        return "resume_intake"
    if date_range_count >= 2 and role_line_count >= 2:
        return "resume_intake"

    return "chat_update"


def capacity_for_mode(mode: ProfileIntakeMode) -> IntakeCapacity:
    return RESUME_INTAKE_CAPACITY if mode == "resume_intake" else CHAT_UPDATE_CAPACITY


def draft_needs_resume_token_budget(current_draft: dict[str, object]) -> bool:
    return any(
        _list_length(current_draft.get(field)) > getattr(CHAT_UPDATE_CAPACITY, attr)
        for field, attr in (
            ("draftFacts", "draft_facts"),
            ("skillClaims", "skill_claims"),
            ("experienceAndProjects", "experience_and_projects"),
            ("evidenceLinks", "evidence_links"),
        )
    )


def max_output_tokens_for_mode(mode: ProfileIntakeMode, current_draft: dict[str, object]) -> tuple[int, str]:
    if mode == "resume_intake":
        return (
            RESUME_INTAKE_MAX_OUTPUT_TOKENS,
            (
                "Resume intake may emit up to 32 facts, 50 skills, 18 experiences, and 20 evidence links; "
                "16000 tokens gives concise JSON room to complete without opening an unbounded response."
            ),
        )
    if draft_needs_resume_token_budget(current_draft):
        return (
            RESUME_INTAKE_MAX_OUTPUT_TOKENS,
            (
                "The saved draft already exceeds compact chat counts, so the resume token budget is used to "
                "return the complete preserved draft safely."
            ),
        )
    return (
        CHAT_UPDATE_MAX_OUTPUT_TOKENS,
        "Compact chat updates should stay small; 5000 tokens covers the schema and preserved small drafts.",
    )


def _list_length(value: object) -> int:
    return len(value) if isinstance(value, list) else 0
