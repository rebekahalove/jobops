import { describe, expect, it } from "vitest";
import { PUBLIC_PORTFOLIO_UNAVAILABLE_MESSAGE, unavailableProfile } from "../../portfolio/lib/unavailable-profile";

describe("public portfolio unavailable profile", () => {
  it("uses a generic public message without internal backend details", () => {
    const profile = unavailableProfile("rebekahalove.dev");
    const publicText = JSON.stringify(profile);

    expect(profile.summary).toBe(PUBLIC_PORTFOLIO_UNAVAILABLE_MESSAGE);
    expect(publicText).not.toContain("JOBOPS_API_BASE_URL");
    expect(publicText).not.toContain("localhost");
    expect(publicText).not.toContain("HTTP 500");
    expect(publicText).not.toContain("request failed");
  });
});
