"use client";

import { useMemo, useState } from "react";
import type { CandidateAnswer, CandidateProfile, RoleFitAnalysis } from "@jobops/contracts";

type ActivePanel = "question" | "role-fit";

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
  profile,
  source
}: {
  profile: CandidateProfile;
  source: "api" | "seed";
}) {
  const [activePanel, setActivePanel] = useState<ActivePanel>("question");
  const [question, setQuestion] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [answer, setAnswer] = useState<CandidateAnswer | null>(null);
  const [roleFit, setRoleFit] = useState<RoleFitAnalysis | null>(null);

  const publishedFactCount = useMemo(
    () =>
      profile.facts.filter(
        (fact) => fact.visibility === "public" && fact.verificationStatus === "published"
      ).length,
    [profile.facts]
  );

  function answerQuestion() {
    setAnswer({
      ...emptyAnswer,
      unknowns: [
        ...emptyAnswer.unknowns,
        question.trim()
          ? `Question asked: "${question.trim()}"`
          : "No question was provided."
      ]
    });
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

  return (
    <main className="page-shell agent-page">
      <section className="agent-header">
        <a className="back-link" href="/">
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
          {publishedFactCount} published facts · {source === "api" ? "API" : "seed"}
        </div>
      </section>

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
            <label htmlFor="candidate-question">Question</label>
            <textarea
              id="candidate-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask about verified experience, education, projects, or skills."
            />
            <button className="primary-action" type="button" onClick={answerQuestion}>
              Ask
            </button>
            {answer ? <AnswerResult answer={answer} /> : null}
          </div>
        ) : (
          <div className="workflow-panel">
            <label htmlFor="job-description">Job description</label>
            <textarea
              id="job-description"
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
    </main>
  );
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
