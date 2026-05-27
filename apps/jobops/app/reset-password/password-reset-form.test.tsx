import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PasswordResetForm } from "./password-reset-form";

describe("PasswordResetForm", () => {
  it("uses the current-password reset path when no token is present", () => {
    const html = renderToStaticMarkup(<PasswordResetForm returnTo="/" username="chance-alpha" />);

    expect(html).toContain('action="/api/dashboard-auth/reset-password"');
    expect(html).toContain('name="currentPassword"');
    expect(html).toContain('name="username"');
  });

  it("uses the token reset path without asking for current password", () => {
    const html = renderToStaticMarkup(
      <PasswordResetForm basePath="/jobops" returnTo="/jobops" token="reset-token" username="" />
    );

    expect(html).toContain('action="/jobops/api/dashboard-auth/confirm-password-reset"');
    expect(html).toContain('type="hidden" name="token" value="reset-token"');
    expect(html).not.toContain('name="currentPassword"');
    expect(html).not.toContain('name="username"');
  });
});
