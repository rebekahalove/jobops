export function PasswordResetForm({
  basePath = "",
  error,
  returnTo,
  username
}: {
  basePath?: "" | "/jobops";
  error?: boolean;
  returnTo: string;
  username: string;
}) {
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="jobops-password-reset-title">
        <p className="eyebrow">JobOps alpha account</p>
        <h1 id="jobops-password-reset-title">Reset your password</h1>
        <p>Your temporary password has expired. Choose a new password to continue.</p>
        <form action={`${basePath}/api/dashboard-auth/reset-password`} className="login-form" method="post">
          <input name="returnTo" type="hidden" value={returnTo} />
          <label>
            <span>Username</span>
            <input autoComplete="username" defaultValue={username} name="username" required type="text" />
          </label>
          <label>
            <span>Current password</span>
            <input autoComplete="current-password" name="currentPassword" required type="password" />
          </label>
          <label>
            <span>New password</span>
            <input autoComplete="new-password" minLength={12} name="newPassword" required type="password" />
          </label>
          {error ? (
            <p className="login-error" role="alert">
              That password reset could not be completed.
            </p>
          ) : null}
          <button className="primary-action button-action" type="submit">
            Save password
          </button>
        </form>
      </section>
    </main>
  );
}
