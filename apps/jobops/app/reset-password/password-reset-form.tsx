import React from "react";

export function PasswordResetForm({
  basePath = "",
  error,
  returnTo,
  token,
  username
}: {
  basePath?: "" | "/jobops";
  error?: boolean;
  returnTo: string;
  token?: string;
  username: string;
}) {
  const isTokenReset = Boolean(token);
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="jobops-password-reset-title">
        <p className="eyebrow">JobOps alpha account</p>
        <h1 id="jobops-password-reset-title">{isTokenReset ? "Choose a new password" : "Reset your password"}</h1>
        <p>{isTokenReset ? "Use the reset link to set a new password." : "Your temporary password has expired. Choose a new password to continue."}</p>
        <form action={`${basePath}/api/dashboard-auth/${isTokenReset ? "confirm-password-reset" : "reset-password"}`} className="login-form" method="post">
          <input name="returnTo" type="hidden" value={returnTo} />
          {isTokenReset ? <input name="token" type="hidden" value={token} /> : null}
          {!isTokenReset ? (
            <>
              <label>
                <span>Username</span>
                <input autoComplete="username" defaultValue={username} name="username" required type="text" />
              </label>
              <label>
                <span>Current password</span>
                <input autoComplete="current-password" name="currentPassword" required type="password" />
              </label>
            </>
          ) : null}
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
          <a className="login-secondary-link" href={`${basePath}/login`}>
            Back to sign in
          </a>
        </form>
      </section>
    </main>
  );
}
