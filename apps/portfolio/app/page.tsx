import Link from "next/link";
import { publicProfile } from "@jobops/profile";

export default function HomePage() {
  const publishedFactCount = publicProfile.facts.filter(
    (fact) => fact.visibility === "public" && fact.verificationStatus === "published"
  ).length;

  return (
    <main className="page-shell">
      <section className="hero">
        <p className="eyebrow">JobOps candidate-agent portfolio</p>
        <h1>{publicProfile.displayName}</h1>
        <p className="lede">{publicProfile.headline}</p>
        <div className="actions">
          <Link className="primary-action" href="/agent">
            Open candidate agent
          </Link>
          <a className="secondary-action" href="#profile-status">
            View profile status
          </a>
        </div>
      </section>

      <section id="profile-status" className="content-band">
        <div>
          <p className="section-kicker">Verified profile status</p>
          <h2>Grounded answers start with approved facts.</h2>
        </div>
        <p>
          This scaffold is wired to the public profile data package, but no detailed
          experience facts have been approved yet. Until facts are published, the
          agent should say what it does not know instead of inventing experience.
        </p>
        <dl className="status-grid">
          <div>
            <dt>Profile state</dt>
            <dd>{publicProfile.profileStatus}</dd>
          </div>
          <div>
            <dt>Published facts</dt>
            <dd>{publishedFactCount}</dd>
          </div>
          <div>
            <dt>Data source</dt>
            <dd>Public seed profile</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
