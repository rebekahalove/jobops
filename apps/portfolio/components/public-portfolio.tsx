import type { CandidateProfile } from "@jobops/contracts";
import { AgentWorkspace } from "./agent-workspace";

export function PublicPortfolio({
  profile,
  source
}: {
  agentHref?: string | null;
  profile: CandidateProfile;
  source: "api" | "seed";
}) {
  const facts = publicFacts(profile);
  const skills = (profile.skillClaims ?? []).filter((skill) => skill.visibility === "public" && skill.publicationStatus === "published");
  const experience = (profile.experienceAndProjects ?? []).filter(
    (item) => item.visibility === "public" && item.publicationStatus === "published"
  );
  const links = (profile.evidenceLinks ?? []).filter((link) => link.visibility === "public" && link.publicationStatus === "published");
  const targetTitles = profile.targetRoleIntent?.targetTitles ?? [];
  const education = experience.filter((item) => item.itemType === "education");
  const certifications = experience.filter((item) => item.itemType === "certification");
  const selectedWork = experience.filter((item) => item.itemType === "experience" || item.itemType === "project");
  const achievements = facts.filter((fact) => looksLikeAchievement(fact.claim, fact.category));
  const hasProfileDetails = Boolean(education.length || certifications.length || links.length);
  const hasProofRail = Boolean(skills.length || achievements.length);
  const isPublished = profile.profileStatus === "published" && Boolean(profile.hasPublishedPublicContent || facts.length || skills.length || experience.length || links.length);

  if (!isPublished) {
    return (
      <main className="page-shell">
        <section className="hero portfolio-hero">
          <p className="eyebrow">JobOps public portfolio</p>
          <h1>Profile not published yet</h1>
          <p className="lede">This alpha portfolio exists, but approved public profile facts have not been published.</p>
          <div className="status-grid">
            <div>
              <dt>Profile state</dt>
              <dd>{profile.profileStatus}</dd>
            </div>
            <div>
              <dt>Published facts</dt>
              <dd>0</dd>
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="page-shell portfolio-page">
      <section className={`hero portfolio-hero${hasProfileDetails ? "" : " solo"}`}>
        <div className="portfolio-hero-copy">
          <p className="eyebrow">JobOps candidate-agent portfolio</p>
          <h1>{profile.displayName}</h1>
          <p className="lede">{profile.headline}</p>
          {profile.summary ? <p className="portfolio-summary">{profile.summary}</p> : null}
          <div className="actions">
            <a className="primary-action" href="#candidate-agent">
              Ask candidate agent
            </a>
          </div>
        </div>

        {hasProfileDetails ? (
          <aside className="portfolio-verification-panel" aria-label="Public profile details">
            <div className="portfolio-panel-header">
              <h2>Education, credentials, and contact.</h2>
            </div>
            <DetailList title="Education" items={education} />
            <DetailList title="Certifications" items={certifications} scroll />
            <PublicLinkList title="Contact & URLs" links={links} />
          </aside>
        ) : null}
      </section>

      <div id="candidate-agent">
        <AgentWorkspace variant="embedded" profile={profile} source={source} />
      </div>

      {targetTitles.length ? (
        <section className="content-band portfolio-section">
          <p className="section-kicker">Role intent</p>
          <h2>Target direction</h2>
          <ChipList items={targetTitles} />
        </section>
      ) : null}

      {facts.length ? (
        <section className="portfolio-facts-band" id="profile-facts">
          <div>
            <p className="section-kicker">Approved facts</p>
            <h2>Public, published information only</h2>
          </div>
          <div className="portfolio-fact-callouts">
            {facts.slice(0, 6).map((fact) => (
              <article className="portfolio-fact-callout" key={fact.id}>
                <p>{fact.claim}</p>
                <span>{fact.category}</span>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {selectedWork.length || hasProofRail ? (
        <section className="portfolio-evidence-layout">
          {selectedWork.length ? (
            <div className="portfolio-work-column">
              <p className="section-kicker">Selected work</p>
              <h2>Featured projects and experience</h2>
            <div className="portfolio-timeline">
              {selectedWork.slice(0, 8).map((item) => (
              <article className="portfolio-card" key={item.id}>
                <p className="section-kicker">{item.itemType}</p>
                <h3>{item.title}</h3>
                {item.organization ? <p>{item.organization}</p> : null}
                {item.startDate || item.endDate || item.location ? (
                  <p className="portfolio-meta">{[joinDates(item.startDate, item.endDate), item.location].filter(Boolean).join(" - ")}</p>
                ) : null}
                <p>{item.summary}</p>
                {item.bullets?.length ? (
                  <ul>
                    {item.bullets.slice(0, 3).map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                ) : null}
              </article>
              ))}
            </div>
            </div>
          ) : null}

          {hasProofRail ? (
            <aside className="portfolio-proof-rail" aria-label="Skills and achievements">
              {skills.length ? (
                <section className="portfolio-rail-section">
                  <p className="section-kicker">Skills</p>
                  <h2>Skills with approved evidence</h2>
                  <div className="portfolio-skill-stack">
                    {skills.slice(0, 12).map((skill) => (
                      <article className="portfolio-card" key={skill.id}>
                        <h3>{skill.skill}</h3>
                        <p>{skill.evidence || skill.category}</p>
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}

              {achievements.length ? (
                <section className="portfolio-rail-section">
                  <p className="section-kicker">Achievements</p>
                  <h2>Selected proof points</h2>
                  <ul className="portfolio-achievement-list">
                    {achievements.slice(0, 8).map((fact) => (
                      <li key={fact.id}>{fact.claim}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </aside>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}

function publicFacts(profile: CandidateProfile) {
  return profile.facts.filter((fact) => fact.visibility === "public" && fact.verificationStatus === "published");
}

function ChipList({ items }: { items: string[] }) {
  return (
    <div className="portfolio-chip-list">
      {items.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
  );
}

function DetailList({
  items,
  scroll = false,
  title
}: {
  items: NonNullable<CandidateProfile["experienceAndProjects"]>;
  scroll?: boolean;
  title: string;
}) {
  if (!items.length) {
    return null;
  }

  return (
    <div className={`portfolio-panel-block${scroll ? " scrollable" : ""}`}>
      <p className="section-kicker">{title}</p>
      <ul className="portfolio-detail-list">
          {items.map((item) => (
            <li key={item.id}>
              <strong>{item.title}</strong>
              {item.organization ? <span>{item.organization}</span> : null}
              {item.endDate || item.location ? <small>{[item.endDate, item.location].filter(Boolean).join(" · ")}</small> : null}
            </li>
          ))}
      </ul>
    </div>
  );
}

function PublicLinkList({
  links,
  title
}: {
  links: NonNullable<CandidateProfile["evidenceLinks"]>;
  title: string;
}) {
  if (!links.length) {
    return null;
  }

  return (
    <div className="portfolio-panel-block">
      <p className="section-kicker">{title}</p>
      <ul className="portfolio-mini-link-list">
          {links.map((link) => (
            <li key={link.id}>
              <a href={link.url} rel="noreferrer" target="_blank">
                {link.label || link.url}
              </a>
            </li>
          ))}
      </ul>
    </div>
  );
}

function looksLikeAchievement(claim: string, category: string) {
  const text = `${category} ${claim}`.toLowerCase();
  return ["achievement", "award", "outcome", "impact", "metric", "increased", "reduced", "saved", "built", "launched", "led"].some((term) =>
    text.includes(term)
  );
}

function joinDates(start?: string | null, end?: string | null) {
  if (start && end) {
    return `${start} - ${end}`;
  }
  return start || end || "";
}
