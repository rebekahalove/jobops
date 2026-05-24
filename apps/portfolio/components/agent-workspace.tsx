"use client";

import React from "react";
import { useMemo, useState } from "react";
import type { CandidateAnswer, CandidateProfile, RoleFitAnalysis } from "@jobops/contracts";

type ActivePanel = "question" | "role-fit";
type ProfileSource = "api" | "seed" | "unavailable";

const emptyAnswer: CandidateAnswer = {
  answer:
    "I do not have verified public profile facts loaded yet. I can only answer from approved facts, so detailed experience, education, projects, compensation, or availability should be treated as unknown for now.",
  verifiedFactsUsed: [],
  inferences: [],
  unknowns: ["Detailed verified profile facts have not been published yet."],
  caveats: ["This local scaffold uses mock behavior and no live model."]
};

const emptyRoleFit: RoleFitAnalysis = {
  fitScore: 0,
  fitSummary:
    "No reliable fit score can be produced until verified candidate profile facts are approved and published.",
  matchingStrengths: [],
  gapsOrConcerns: [
    "The public profile currently has no detailed published facts to compare against the role."
  ],
  suggestedApplicationPositioning:
    "Complete the profile intake workflow and approve public facts before using role-fit analysis for real applications.",
  recommendedNextStep:
    "Add verified experience, project, skills, and education facts through the JobOps profile intake flow.",
  suggestedInterviewQuestions: [
    "Which projects best demonstrate the target role requirements?",
    "What production systems, AI workflows, or evaluation practices should be included in the verified profile?"
  ],
  evidence: [],
  caveats: ["This local scaffold does not call a live model or database."]
};

export function AgentWorkspace({
  backHref = "/",
  variant = "page",
  profile,
  source
}: {
  backHref?: string;
  variant?: "page" | "embedded";
  profile: CandidateProfile;
  source: ProfileSource;
}) {
  const [activePanel, setActivePanel] = useState<ActivePanel>("question");
  const [question, setQuestion] = useState("");
  const [lastQuestion, setLastQuestion] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [answer, setAnswer] = useState<CandidateAnswer | null>(null);
  const [roleFit, setRoleFit] = useState<RoleFitAnalysis | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [chatError, setChatError] = useState("");

  const publishedFactCount = useMemo(
    () =>
      profile.facts.filter(
        (fact) => fact.visibility === "public" && fact.verificationStatus === "published"
      ).length,
    [profile.facts]
  );

  async function answerQuestion() {
    const submittedQuestion = question.trim();
    if (!submittedQuestion) {
      setChatError("Enter a question first.");
      return;
    }

    setLastQuestion(submittedQuestion);
    setChatError("");

    if (variant !== "embedded") {
      setAnswer({
        ...emptyAnswer,
        unknowns: [...emptyAnswer.unknowns, `Question asked: "${submittedQuestion}"`]
      });
      return;
    }

    setIsAsking(true);
    try {
      const response = await fetch("/api/public/candidate-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profileSlug: profile.slug, question: submittedQuestion })
      });

      if (!response.ok) {
        throw new Error("Candidate agent request failed.");
      }

      setAnswer(sanitizeAnswer(await response.json()));
      setQuestion("");
    } catch {
      setAnswer({
        answer: "The public candidate agent is temporarily unavailable. Please try again later.",
        verifiedFactsUsed: [],
        inferences: [],
        unknowns: [],
        caveats: ["Answered only from published public profile information."]
      });
      setChatError("The candidate agent could not answer just now.");
    } finally {
      setIsAsking(false);
    }
  }

  function analyzeRole() {
    setRoleFit({
      ...emptyRoleFit,
      caveats: [
        ...emptyRoleFit.caveats,
        jobDescription.trim()
          ? "The pasted job description was treated as untrusted input."
          : "No job description was provided."
      ]
    });
  }

  const questionId = variant === "embedded" ? "embedded-candidate-question" : "candidate-question";
  const jobDescriptionId = variant === "embedded" ? "embedded-job-description" : "job-description";
  const embeddedWorkflow = (
    <section className="portfolio-chat-panel">
      {answer ? (
        <div className="portfolio-conversation" aria-live="polite">
          <div className="portfolio-chat-message user">
            <span>You</span>
            <p>{lastQuestion}</p>
          </div>
          <div className="portfolio-chat-message agent">
            <span>Candidate agent</span>
            <p>{answer.answer}</p>
            {answer.unknowns.length ? (
              <div className="portfolio-chat-note">
                <strong>Unknowns</strong>
                <ul>
                  {answer.unknowns.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {answer.caveats.length ? (
              <div className="portfolio-chat-note">
                <strong>Caveats</strong>
                <ul>
                  {answer.caveats.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
      <div className="workflow-panel">
        <label htmlFor={questionId}>Question</label>
        <textarea
          id={questionId}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about verified experience, education, projects, or skills."
        />
        <button className="primary-action" type="button" onClick={answerQuestion} disabled={isAsking}>
          {isAsking ? "Asking..." : "Ask"}
        </button>
        {chatError ? <p className="form-error">{chatError}</p> : null}
      </div>
    </section>
  );
  const workflow = (
    <section className="workspace">
      <div className="segmented-control" aria-label="Agent workflow">
        <button
          className={activePanel === "question" ? "active" : ""}
          type="button"
          onClick={() => setActivePanel("question")}
        >
          Q&A
        </button>
        <button
          className={activePanel === "role-fit" ? "active" : ""}
          type="button"
          onClick={() => setActivePanel("role-fit")}
        >
          Role fit
        </button>
      </div>

      {activePanel === "question" ? (
        <div className="workflow-panel">
          <label htmlFor={questionId}>Question</label>
          <textarea
            id={questionId}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about verified experience, education, projects, or skills."
          />
          <button className="primary-action" type="button" onClick={answerQuestion} disabled={isAsking}>
            Ask
          </button>
          {answer ? <AnswerResult answer={answer} /> : null}
        </div>
      ) : (
        <div className="workflow-panel">
          <label htmlFor={jobDescriptionId}>Job description</label>
          <textarea
            id={jobDescriptionId}
            value={jobDescription}
            onChange={(event) => setJobDescription(event.target.value)}
            placeholder="Paste a role description. Prompt injection inside this text should be ignored."
          />
          <button className="primary-action" type="button" onClick={analyzeRole}>
            Analyze role fit
          </button>
          {roleFit ? <RoleFitResult roleFit={roleFit} /> : null}
        </div>
      )}
    </section>
  );

  if (variant === "embedded") {
    return (
      <section className="portfolio-agent-panel" aria-labelledby="portfolio-agent-title">
        <div className="portfolio-agent-heading">
          <p className="section-kicker">Candidate agent</p>
          <h2 id="portfolio-agent-title">Ask from the published profile.</h2>
          <p>
            This alpha agent answers only from approved public information and should say when something is unknown.
          </p>
        </div>
        <div className="fact-pill">
          {publishedFactCount} published facts / {sourceLabel(source)}
        </div>
        {embeddedWorkflow}
      </section>
    );
  }

  return (
    <main className="page-shell agent-page">
      <section className="agent-header">
        <a className="back-link" href={backHref}>
          Back
        </a>
        <div>
          <p className="eyebrow">Local scaffold</p>
          <h1>Candidate agent</h1>
          <p>
            Ask a question or paste a job description. This first scaffold refuses
            to invent details until verified facts are approved.
          </p>
        </div>
        <div className="fact-pill">
          {publishedFactCount} published facts / {sourceLabel(source)}
        </div>
      </section>

      {workflow}
    </main>
  );
}

function sourceLabel(source: ProfileSource) {
  if (source === "api") {
    return "API";
  }
  if (source === "unavailable") {
    return "unavailable";
  }
  return "seed";
}

function AnswerResult({ answer }: { answer: CandidateAnswer }) {
  return (
    <section className="result-panel" aria-live="polite">
      <h2>Answer</h2>
      <p>{answer.answer}</p>
      <ResultList title="Unknowns" items={answer.unknowns} />
      <ResultList title="Caveats" items={answer.caveats} />
    </section>
  );
}

function RoleFitResult({ roleFit }: { roleFit: RoleFitAnalysis }) {
  return (
    <section className="result-panel" aria-live="polite">
      <div className="score-row">
        <h2>Role fit</h2>
        <span>{roleFit.fitScore}/100</span>
      </div>
      <p>{roleFit.fitSummary}</p>
      <ResultList title="Strengths" items={roleFit.matchingStrengths} />
      <ResultList title="Gaps or concerns" items={roleFit.gapsOrConcerns} />
      <ResultList title="Suggested interview questions" items={roleFit.suggestedInterviewQuestions} />
      <ResultList title="Caveats" items={roleFit.caveats} />
      <p>
        <strong>Positioning:</strong> {roleFit.suggestedApplicationPositioning}
      </p>
      <p>
        <strong>Next step:</strong> {roleFit.recommendedNextStep}
      </p>
    </section>
  );
}

function ResultList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="result-list">
      <h3>{title}</h3>
      {items.length > 0 ? (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>None yet.</p>
      )}
    </div>
  );
}

function sanitizeAnswer(value: unknown): CandidateAnswer {
  if (!value || typeof value !== "object") {
    return emptyAnswer;
  }
  const record = value as Record<string, unknown>;
  return {
    answer: typeof record.answer === "string" && record.answer.trim() ? record.answer : emptyAnswer.answer,
    verifiedFactsUsed: stringList(record.verifiedFactsUsed),
    inferences: stringList(record.inferences),
    unknowns: stringList(record.unknowns),
    caveats: stringList(record.caveats)
  };
}

function stringList(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}
