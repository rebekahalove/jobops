export function DashboardLogin({
  basePath = "",
  error,
  returnTo
}: {
  basePath?: "" | "/jobops";
  error?: boolean;
  returnTo: string;
}) {
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="jobops-private-preview-title">
        <p className="eyebrow">JobOps private preview</p>
        <h1 id="jobops-private-preview-title">Sign in to JobOps</h1>
        <p>This dashboard uses persisted alpha user sessions.</p>
        <form action={`${basePath}/api/dashboard-auth/login`} className="login-form" method="post">
          <input name="returnTo" type="hidden" value={returnTo} />
          <label>
            <span>Username</span>
            <input autoComplete="username" name="username" required suppressHydrationWarning type="text" />
          </label>
          <label>
            <span>Password</span>
            <input autoComplete="current-password" name="password" required suppressHydrationWarning type="password" />
          </label>
          {error ? (
            <p className="login-error" role="alert">
              That username and password did not match an active JobOps alpha user.
            </p>
          ) : null}
          <button className="primary-action button-action" suppressHydrationWarning type="submit">
            Continue
          </button>
        </form>
      </section>
    </main>
  );
}
