import Link from "next/link";

export default function PrivacyPage() {
  return (
    <main className="privacy-page-shell">
      <header className="public-alpha-nav privacy-page-nav" aria-label="JobOps privacy navigation">
        <Link className="brand" href="/about">
          <span>JobOps</span>
          <small>Alpha privacy</small>
        </Link>
        <nav>
          <Link href="/about">About JobOps</Link>
          <Link href="/login">Log in</Link>
        </nav>
      </header>
      <section className="login-panel privacy-policy-panel" aria-labelledby="jobops-alpha-privacy-title">
        <p className="eyebrow">JobOps alpha privacy</p>
        <h1 id="jobops-alpha-privacy-title">Alpha privacy policy</h1>
        <p>
          JobOps stores the information needed to run your private alpha workspace: account details, profile data,
          target companies, jobs, applications, command/chat interactions, generated outputs, and operational logs or
          debugging records.
        </p>
        <p>JobOps uses essential HttpOnly session cookies for sign-in. No analytics, ads, or session replay are used unless they are added and disclosed later.</p>
        <p>
          When you ask JobOps for profile, job, company, or application assistance, your provided content may be sent to
          configured model providers so they can generate drafts, summaries, recommendations, or structured updates.
        </p>
        <p>Please avoid highly sensitive information during alpha testing.</p>
        <p>
          You can change your password, request password recovery, and delete your profile/account from the account
          settings page. Deletion is permanent for this alpha workspace.
        </p>
        <p>For privacy or support questions, contact the JobOps/Rebekah alpha support path used for your invite.</p>
      </section>
    </main>
  );
}
