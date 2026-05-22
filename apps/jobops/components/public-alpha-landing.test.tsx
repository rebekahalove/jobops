import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PublicAlphaLanding } from "./public-alpha-landing";

const metrics = [
  { id: "users", label: "Users onboarded", value: null },
  { id: "jobs", label: "Jobs saved", value: 0 }
];

describe("PublicAlphaLanding", () => {
  it("renders login and request-access CTAs for logged-out visitors", () => {
    const html = renderToStaticMarkup(<PublicAlphaLanding initialMetrics={metrics} />);

    expect(html).toContain("Log in");
    expect(html).toContain("Request alpha access");
    expect(html).not.toContain("Back to command center");
    expect(html).not.toContain("Open command center");
  });

  it("renders command-center CTAs for authenticated visitors", () => {
    const html = renderToStaticMarkup(
      <PublicAlphaLanding
        auth={{
          isAuthenticated: true,
          user: { username: "chance-alpha" },
          workspace: { slug: "chance-alpha" },
          candidateProfile: { slug: "chance-alpha" }
        }}
        initialMetrics={metrics}
      />
    );

    expect(html).toContain("Back to command center");
    expect(html).toContain("Open command center");
    expect(html).toContain("Request alpha access");
    expect(html).not.toContain(">Log in<");
  });

  it("renders stale or invalid sessions as logged out", () => {
    const html = renderToStaticMarkup(<PublicAlphaLanding auth={{ isAuthenticated: false }} initialMetrics={metrics} />);

    expect(html).toContain("Log in");
    expect(html).not.toContain("Back to command center");
  });
});
