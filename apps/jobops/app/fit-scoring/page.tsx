import Link from "next/link";

export default function FitScoringPage() {
  return (
    <main className="dashboard-main">
      <section className="placeholder-panel" aria-labelledby="fit-scoring-title">
        <Link className="back-link" href="/">
          Back to command center
        </Link>
        <p className="eyebrow">Deferred workflow</p>
        <h1 id="fit-scoring-title">Fit Scoring</h1>
        <p>Fit analysis will return as a backend-owned agent action from saved jobs and profile data.</p>
        <div className="empty-state-block">
          <h2>Coming into focus</h2>
          <p>For now, job prioritization routes through the Jobs workspace and remains mocked in the command center.</p>
        </div>
      </section>
    </main>
  );
}
