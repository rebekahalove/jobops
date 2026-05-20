"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import type { PublicJobOpsMetric } from "../lib/public-jobops";

type FormState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

const focusItems = [
  "Profile and portfolio building",
  "Company tracking",
  "AI-assisted workflow commands",
  "Application tracking",
  "Human-in-the-loop review",
  "Metrics and self-improvement loops"
];

export function PublicAlphaLanding({
  basePath = "",
  initialMetrics
}: {
  basePath?: "" | "/jobops";
  initialMetrics: PublicJobOpsMetric[];
}) {
  const [formState, setFormState] = useState<FormState>({ status: "idle" });
  const metrics = useMemo(() => initialMetrics, [initialMetrics]);
  const loginHref = `${basePath}/login?returnTo=${encodeURIComponent(basePath || "/")}`;
  const dashboardHref = basePath || "/";

  async function submitAccessRequest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const name = stringValue(formData.get("name"));
    const email = stringValue(formData.get("email"));
    const note = stringValue(formData.get("note"));

    if (!name || !email) {
      setFormState({ status: "error", message: "Please add your name and email." });
      return;
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      setFormState({ status: "error", message: "Please enter a valid email address." });
      return;
    }

    setFormState({ status: "submitting" });
    const response = await fetch(`${basePath}/api/public/jobops/access-requests`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        name,
        email,
        note: note || undefined
      })
    });

    if (!response.ok) {
      setFormState({ status: "error", message: "The request could not be saved. Please try again soon." });
      return;
    }

    form.reset();
    setFormState({ status: "success", message: "Thanks. Your alpha access request was received." });
  }

  return (
    <main className="public-alpha-shell">
      <header className="public-alpha-nav" aria-label="JobOps public navigation">
        <Link className="brand" href={dashboardHref}>
          <span>JobOps</span>
          <small>Public alpha</small>
        </Link>
        <nav>
          <a href="https://github.com/rebekahalove/jobops">GitHub</a>
          <Link href={loginHref}>Log in</Link>
        </nav>
      </header>

      <section className="public-alpha-hero" aria-labelledby="jobops-alpha-title">
        <div className="public-alpha-copy">
          <p className="eyebrow">Early alpha / build in public</p>
          <h1 id="jobops-alpha-title">JobOps</h1>
          <p className="public-alpha-lede">
            An AI-assisted command center for job search operations. It is being built in public as a practical applied AI engineering demo, with a bias toward workflow automation, human review, and measurable improvement.
          </p>
          <div className="public-alpha-actions">
            <a className="primary-action" href="#alpha-access">
              Request alpha access
            </a>
            <Link className="secondary-action" href={loginHref}>
              Log in
            </Link>
          </div>
        </div>
        <div className="public-product-preview" aria-label="JobOps command center preview">
          <div className="preview-toolbar">
            <span>Command center</span>
            <strong>human reviewed</strong>
          </div>
          <div className="preview-command">Add Acme AI to my target companies and check whether they have applied AI platform roles.</div>
          <div className="preview-grid">
            <span>Profile draft</span>
            <span>Companies</span>
            <span>Applications</span>
            <span>Metrics loop</span>
          </div>
        </div>
      </section>

      <section className="public-alpha-band" aria-labelledby="current-focus-title">
        <div>
          <p className="eyebrow">Current focus</p>
          <h2 id="current-focus-title">Small, inspectable systems for real job-search work.</h2>
          <p>
            The alpha is deliberately narrow: organize the work, keep private data tenant-scoped, let AI propose structured actions, and leave meaningful decisions with the person using it.
          </p>
        </div>
        <ul className="focus-list">
          {focusItems.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="public-alpha-band" aria-labelledby="public-metrics-title">
        <div>
          <p className="eyebrow">Public metrics</p>
          <h2 id="public-metrics-title">Harmless aggregate snapshot.</h2>
          <p>
            These numbers are intentionally aggregate-only. They do not expose user names, emails, companies tied to a user, profile content, application details, raw logs, or private notes.
          </p>
        </div>
        <dl className="public-metrics-grid">
          {metrics.map((item) => (
            <div key={item.id}>
              <dt>{item.label}</dt>
              <dd>{item.value.toLocaleString()}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="public-alpha-band access-band" id="alpha-access" aria-labelledby="alpha-access-title">
        <div>
          <p className="eyebrow">Request access</p>
          <h2 id="alpha-access-title">Interested in trying the alpha?</h2>
          <p>
            Share a name, email, and optional use case. This only records the request; no emails are sent yet.
          </p>
        </div>
        <form className="alpha-access-form" onSubmit={submitAccessRequest}>
          <label>
            <span>Name</span>
            <input autoComplete="name" maxLength={200} name="name" required type="text" />
          </label>
          <label>
            <span>Email</span>
            <input autoComplete="email" maxLength={320} name="email" required type="email" />
          </label>
          <label className="full-span">
            <span>Optional note or use case</span>
            <textarea maxLength={2000} name="note" />
          </label>
          {formState.status === "error" || formState.status === "success" ? (
            <p className={`form-message ${formState.status}`} role={formState.status === "error" ? "alert" : "status"}>
              {formState.message}
            </p>
          ) : null}
          <button className="primary-action button-action" disabled={formState.status === "submitting"} type="submit">
            {formState.status === "submitting" ? "Sending request..." : "Request alpha access"}
          </button>
        </form>
      </section>
    </main>
  );
}

function stringValue(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value.trim() : "";
}
