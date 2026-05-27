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
});
