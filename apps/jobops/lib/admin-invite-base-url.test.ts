import { describe, expect, it } from "vitest";
import { withInviteBaseUrl } from "./admin-invite-base-url";

describe("admin invite base URL", () => {
  it("uses the mounted JobOps origin for portfolio requests", () => {
    const request = new Request("https://rebekahalove.dev/jobops/api/admin/invitations");

    expect(withInviteBaseUrl(request, { email: "casey@example.com" })).toEqual({
      email: "casey@example.com",
      invite_base_url: "https://rebekahalove.dev/jobops"
    });
  });

  it("preserves explicit invite base URLs", () => {
    const request = new Request("https://rebekahalove.dev/jobops/api/admin/invitations");

    expect(withInviteBaseUrl(request, { invite_base_url: "https://custom.example.com/jobs" })).toEqual({
      invite_base_url: "https://custom.example.com/jobs"
    });
  });

  it("prefers configured public app base URL over the proxied request origin", () => {
    const previous = process.env.JOBOPS_APP_BASE_URL;
    process.env.JOBOPS_APP_BASE_URL = "https://rebekahalove.dev/jobops";
    try {
      const request = new Request("http://rebekahalove.dev:80/jobops/api/admin/invitations");

      expect(withInviteBaseUrl(request, { email: "casey@example.com" })).toEqual({
        email: "casey@example.com",
        invite_base_url: "https://rebekahalove.dev/jobops"
      });
    } finally {
      if (previous === undefined) {
        delete process.env.JOBOPS_APP_BASE_URL;
      } else {
        process.env.JOBOPS_APP_BASE_URL = previous;
      }
    }
  });

  it("canonicalizes public proxy origins to https and strips default ports", () => {
    const request = new Request("http://rebekahalove.dev:80/jobops/api/admin/invitations", {
      headers: {
        host: "rebekahalove.dev:80"
      }
    });

    expect(withInviteBaseUrl(request, { email: "casey@example.com" })).toEqual({
      email: "casey@example.com",
      invite_base_url: "https://rebekahalove.dev/jobops"
    });
  });
});
