export function InviteAcceptForm({ basePath = "", token }: { basePath?: "" | "/jobops"; token: string }) {
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="jobops-invite-title">
        <p className="eyebrow">JobOps alpha invite</p>
        <h1 id="jobops-invite-title">Accept your workspace invite</h1>
        <p>Create your private JobOps alpha account.</p>
        <form action={`${basePath}/api/invites/accept`} className="login-form" method="post">
          <input name="token" type="hidden" value={token} />
          <label>
            <span>Display name</span>
            <input autoComplete="name" name="displayName" required type="text" />
          </label>
          <label>
            <span>Username</span>
            <input autoComplete="username" name="username" required type="text" />
          </label>
          <label>
            <span>Password</span>
            <input autoComplete="new-password" name="password" minLength={12} required type="password" />
          </label>
          <button className="primary-action button-action" type="submit">
            Create account
          </button>
        </form>
      </section>
    </main>
  );
}
