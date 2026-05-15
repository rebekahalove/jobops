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
        <h1 id="jobops-private-preview-title">Enter the preview password</h1>
        <p>This dashboard is behind a temporary construction gate while private workflows are still in progress.</p>
        <form action={`${basePath}/api/dashboard-auth/login`} className="login-form" method="post">
          <input name="returnTo" type="hidden" value={returnTo} />
          <label>
            <span>Password</span>
            <input autoComplete="current-password" autoFocus name="password" required type="password" />
          </label>
          {error ? (
            <p className="login-error" role="alert">
              That password did not unlock the private preview.
            </p>
          ) : null}
          <button className="primary-action button-action" type="submit">
            Continue
          </button>
        </form>
      </section>
    </main>
  );
}
