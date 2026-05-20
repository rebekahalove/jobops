export default function PrivacyPage() {
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="jobops-alpha-privacy-title">
        <p className="eyebrow">JobOps alpha privacy</p>
        <h1 id="jobops-alpha-privacy-title">Alpha privacy note</h1>
        <p>JobOps uses essential HttpOnly session cookies for authentication.</p>
        <p>
          During the alpha, JobOps may store profile, company, job, application, command-center interaction, action log,
          debugging, and error data so the product can be tested and improved.
        </p>
        <p>Please do not enter highly sensitive information while JobOps is in alpha.</p>
        <p>No analytics, advertising, session replay, or other non-essential cookies are introduced in this branch.</p>
        <p>
          TODO before beta or public launch: publish a full privacy policy and terms, add cookie notice/preferences if
          analytics or non-essential cookies are introduced, and define export/delete data processes.
        </p>
      </section>
    </main>
  );
}
