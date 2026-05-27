import React from "react";

export function ForgotPasswordForm({ basePath = "", sent = false }: { basePath?: "" | "/jobops"; sent?: boolean }) {
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="jobops-forgot-password-title">
        <p className="eyebrow">JobOps alpha account</p>
        <h1 id="jobops-forgot-password-title">Password recovery</h1>
        <p>Enter your JobOps username or email and we will send reset instructions if an alpha account exists.</p>
        <form action={`${basePath}/api/dashboard-auth/request-password-reset`} className="login-form" method="post">
          <label>
            <span>Username or email</span>
            <input autoComplete="username" name="identifier" required type="text" />
          </label>
          {sent ? <p className="login-success">If an account exists, reset instructions have been sent.</p> : null}
          <button className="primary-action button-action" type="submit">
            Send reset link
          </button>
          <a className="login-secondary-link" href={`${basePath}/login`}>
            Back to sign in
          </a>
        </form>
      </section>
    </main>
  );
}
