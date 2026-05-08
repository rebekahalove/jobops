import { describe, expect, it } from "vitest";
import { getPublishedFacts, publicProfile } from "./index";

describe("public profile seed", () => {
  it("starts as a draft profile without invented published facts", () => {
    expect(publicProfile.slug).toBe("rebekah-love");
    expect(publicProfile.profileStatus).toBe("draft");
    expect(getPublishedFacts(publicProfile)).toEqual([]);
  });
});
