import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ForgotPasswordForm } from "./forgot-password-form";

describe("ForgotPasswordForm", () => {
  it("uses standalone routes by default", () => {
    const html = renderToStaticMarkup(<ForgotPasswordForm />);

    expect(html).toContain('action="/api/dashboard-auth/request-password-reset"');
    expect(html).toContain('href="/login"');
  });

  it("uses mounted JobOps routes when rendered under the portfolio app", () => {
    const html = renderToStaticMarkup(<ForgotPasswordForm basePath="/jobops" sent />);

    expect(html).toContain('action="/jobops/api/dashboard-auth/request-password-reset"');
    expect(html).toContain('href="/jobops/login"');
    expect(html).toContain("reset instructions have been sent");
  });
});
