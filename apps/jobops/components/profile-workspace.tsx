"use client";

import React, { useState } from "react";
import {
  createMockProfileDraft,
  emptyTargetRoleIntent,
  type MockProfileDraft,
  type TargetRoleIntent
} from "../lib/profile-intake";

type IntentField = keyof TargetRoleIntent;

export function ProfileWorkspace() {
  const [intent, setIntent] = useState<TargetRoleIntent>(emptyTargetRoleIntent);
  const [resumeText, setResumeText] = useState("");
  const [draft, setDraft] = useState<MockProfileDraft | null>(null);

  function updateIntent(field: IntentField, value: string) {
    setIntent((current) => ({
      ...current,
      [field]: value
    }));
  }

  function generateDraftProfile() {
    setDraft(createMockProfileDraft(resumeText, intent));
  }

  return (
    <main className="dashboard-main profile-workspace">
      <section className="page-heading" aria-labelledby="profile-title">
        <p className="eyebrow">Profile workspace</p>
        <h1 id="profile-title">Your structured profile powers JobOps.</h1>
        <p>
          This workspace will turn resume text and follow-up answers into draft career data for review. Nothing here is
          verified, public, or persisted yet.
        </p>
      </section>

      <section className="intake-grid" aria-label="Profile intake steps">
        <article className="intake-panel">
          <div>
            <p className="eyebrow">Step 1</p>
            <h2>Target role intent</h2>
            <p>Start with what you want next so the extractor can look for the right evidence.</p>
          </div>

          <div className="intent-form" aria-label="Target role intent form">
            <label>
              Target titles
              <input
                onChange={(event) => updateIntent("targetTitles", event.target.value)}
                placeholder="Applied AI Engineer, Forward Deployed Engineer"
                suppressHydrationWarning
                value={intent.targetTitles}
              />
            </label>
            <label>
              Target role families
              <input
                onChange={(event) => updateIntent("roleFamilies", event.target.value)}
                placeholder="LLM systems, product engineering, evals"
                suppressHydrationWarning
                value={intent.roleFamilies}
              />
            </label>
            <label>
              Preferred work mode
              <select
                onChange={(event) => updateIntent("preferredWorkMode", event.target.value)}
                suppressHydrationWarning
                value={intent.preferredWorkMode}
              >
                <option value="flexible">Flexible</option>
                <option value="remote">Remote</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">Onsite</option>
              </select>
            </label>
            <label>
              Preferred locations
              <input
                onChange={(event) => updateIntent("preferredLocations", event.target.value)}
                placeholder="Remote US, Raleigh-Durham, NYC"
                suppressHydrationWarning
                value={intent.preferredLocations}
              />
            </label>
            <label>
              Domains or industries of interest
              <input
                onChange={(event) => updateIntent("domainsOfInterest", event.target.value)}
                placeholder="Developer tools, education, healthcare, enterprise AI"
                suppressHydrationWarning
                value={intent.domainsOfInterest}
              />
            </label>
            <label>
              Dealbreakers or constraints
              <textarea
                className="small-textarea"
                onChange={(event) => updateIntent("constraints", event.target.value)}
                placeholder="Travel, location, timeline, role scope, sponsorship, compensation constraints"
                suppressHydrationWarning
                value={intent.constraints}
              />
            </label>
          </div>
        </article>

        <article className="intake-panel">
          <div>
            <p className="eyebrow">Step 2</p>
            <h2>Resume intake</h2>
            <p>Paste resume text for a deterministic local mock extraction. Raw resume text is not stored.</p>
          </div>

          <label>
            Resume text
            <textarea
              onChange={(event) => setResumeText(event.target.value)}
              placeholder="Paste resume text here..."
              suppressHydrationWarning
              value={resumeText}
            />
          </label>

          <label>
            Resume file upload
            <input disabled suppressHydrationWarning type="file" />
            <span className="field-note">Upload will be added later. Paste text for this shell.</span>
          </label>

          <button
            className="primary-action button-action"
            onClick={generateDraftProfile}
            suppressHydrationWarning
            type="button"
          >
            Generate draft profile
          </button>
        </article>
      </section>

      <section className="intake-panel" aria-labelledby="draft-preview-title">
        <div>
          <p className="eyebrow">Step 3</p>
          <h2 id="draft-preview-title">Draft profile preview</h2>
          <p>Mock output is draft, resume-derived, not verified, private, and not published.</p>
        </div>
        <DraftProfilePreview draft={draft} />
      </section>

      <section className="intake-panel" aria-labelledby="questions-title">
        <div>
          <p className="eyebrow">Step 4</p>
          <h2 id="questions-title">Clarifying questions</h2>
          <p>These questions will become the first profile generator follow-up loop.</p>
        </div>
        <ClarifyingQuestions draft={draft} />
      </section>
    </main>
  );
}

function DraftProfilePreview({ draft }: { draft: MockProfileDraft | null }) {
  if (!draft) {
    return (
      <div className="empty-state-block">
        <h3>No draft yet</h3>
        <p>Paste resume text and generate a draft profile to preview resume-derived claims.</p>
      </div>
    );
  }

  return (
    <div className="profile-preview-grid">
      <PreviewColumn title="Draft facts">
        {draft.facts.map((fact) => (
          <li key={fact.id}>
            <strong>{fact.category}</strong>
            <span>{fact.claim}</span>
            <small>
              {fact.reviewStatus} / {fact.source} / {fact.verificationStatus} / {fact.visibility}
            </small>
          </li>
        ))}
      </PreviewColumn>

      <PreviewColumn title="Skill claims">
        {draft.skillClaims.length ? (
          draft.skillClaims.map((skill) => (
            <li key={skill.id}>
              <strong>{skill.skill}</strong>
              <span>{skill.evidence}</span>
              <small>
                {skill.source} / {skill.verificationStatus}
              </small>
            </li>
          ))
        ) : (
          <li>No skill claims detected by the mock extractor.</li>
        )}
      </PreviewColumn>

      <PreviewColumn title="Experience summaries">
        {draft.experienceSummaries.map((experience) => (
          <li key={experience.id}>
            <strong>{experience.title}</strong>
            <span>{experience.summary}</span>
            <small>
              {experience.source} / {experience.verificationStatus}
            </small>
          </li>
        ))}
      </PreviewColumn>

      <PreviewColumn title="Human-approved facts">
        <li>Empty. Candidate review and approval are intentionally deferred.</li>
      </PreviewColumn>

      <PreviewColumn title="Public/published facts">
        <li>Empty. Public candidate-agent facts must be explicitly approved and published later.</li>
      </PreviewColumn>

      <PreviewColumn title="Links">
        {draft.links.length ? draft.links.map((link) => <li key={link}>{link}</li>) : <li>No links detected.</li>}
      </PreviewColumn>
    </div>
  );
}

function ClarifyingQuestions({ draft }: { draft: MockProfileDraft | null }) {
  if (!draft) {
    return (
      <div className="empty-state-block">
        <h3>No questions yet</h3>
        <p>Generate a draft profile to see applied AI and FDE-oriented follow-up questions.</p>
      </div>
    );
  }

  return (
    <ol className="question-list">
      {draft.clarifyingQuestions.map((question) => (
        <li key={question.id}>
          <strong>{question.topic}</strong>
          <span>{question.question}</span>
        </li>
      ))}
    </ol>
  );
}

function PreviewColumn({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <section className="preview-column">
      <h3>{title}</h3>
      <ul>{children}</ul>
    </section>
  );
}
