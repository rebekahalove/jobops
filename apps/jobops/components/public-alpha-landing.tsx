"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import type { JobOpsServerSession } from "../lib/jobops-session-contract";
import type { PublicJobOpsMetric } from "../lib/public-jobops";

type FormState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

const workflowItems = [
  "Start by pasting your resume to build a reusable profile",
  "Save your skills, experience, goals, locations, and target roles",
  "Track companies you want to follow for future openings",
  "Save jobs, notes, statuses, and application activity",
  "Draft tailored materials from your saved profile and the target job",
  "Store cover letters, notes, and drafts with the application they belong to",
  "Review what you sent before recruiter calls or interviews",
  "Use natural language to update your search without managing a spreadsheet by hand"
];

const availableNowItems = [
  "Public alpha page and request-access form",
  "Private alpha login",
  "Early profile, company, job, and application tracking",
  "Public repo for following the build"
];

const comingNextItems = [
  "Resume-to-profile onboarding",
  "Tailored cover letters and outreach drafts saved to applications",
  "Reusable company records and job discovery support",
  "Better application follow-up tracking",
  "Profile publishing and portfolio support",
  "Search metrics and feedback loops"
];

export function PublicAlphaLanding({
  auth = { isAuthenticated: false },
  basePath = "",
  initialMetrics
}: {
  auth?: JobOpsServerSession;
  basePath?: "" | "/jobops";
  initialMetrics: PublicJobOpsMetric[];
}) {
  const [formState, setFormState] = useState<FormState>({ status: "idle" });
  const metrics = useMemo(() => initialMetrics, [initialMetrics]);
  const loginHref = `${basePath}/login?returnTo=${encodeURIComponent(basePath || "/")}`;
  const dashboardHref = basePath || "/";
  const isAuthenticated = auth.isAuthenticated;

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
    setFormState({
      status: "success",
      message:
        "Thanks — your alpha access request was received. I’ll review requests as JobOps becomes ready for more alpha users."
    });
  }

  return (
    <main className="public-alpha-shell">
      <header className="public-alpha-nav" aria-label="JobOps public navigation">
        <Link className="brand" href={dashboardHref}>
          <span>JobOps</span>
          <small>Public alpha</small>
        </Link>
        <nav>
          <a href="https://github.com/rebekahalove/jobops">View the public repo</a>
          <Link href={isAuthenticated ? dashboardHref : loginHref}>
            {isAuthenticated ? "Open command center" : "Log in"}
          </Link>
        </nav>
      </header>

      <section className="public-alpha-hero" aria-labelledby="jobops-alpha-title">
        <div className="public-alpha-copy">
          <p className="eyebrow">Early alpha / building in public</p>
          <h1 id="jobops-alpha-title">Use AI for your job search without starting over every time.</h1>
          <p className="public-alpha-lede">
            JobOps saves your profile, target companies, jobs, application materials, and follow-ups so AI can help
            with each next step using the context you already gave it.
          </p>
          <div className="public-alpha-actions">
            <Link className="primary-action" href={isAuthenticated ? dashboardHref : loginHref}>
              {isAuthenticated ? "Back to command center" : "Log in"}
            </Link>
            <a className="secondary-action" href="#alpha-access">
              Request alpha access
            </a>
            <a className="secondary-action" href="https://github.com/rebekahalove/jobops">
              View the public repo
            </a>
          </div>
        </div>
        <div className="public-product-preview" aria-label="JobOps command center preview">
          <div className="preview-toolbar">
            <span>Job search command center</span>
            <strong>context saved</strong>
          </div>
          <div className="preview-command">
            Save this job, draft a tailored cover letter using my profile, and attach it to the application so I can
            review it later.
          </div>
          <div className="preview-grid">
            <span>Profile</span>
            <span>Companies</span>
            <span>Jobs</span>
            <span>Applications</span>
          </div>
        </div>
      </section>

      <section className="public-alpha-band" aria-labelledby="why-jobops-title">
        <div>
          <p className="eyebrow">Why this exists</p>
          <h2 id="why-jobops-title">ChatGPT can help. JobOps helps it remember.</h2>
          <p>
            You can already ask AI to write a cover letter, improve your resume, or help prep for an interview. The
            frustrating part is having to re-upload your resume, paste the job description, explain your goals, and
            repeat your preferences every time.
          </p>
          <p>
            JobOps is being built around the missing layer: saved job-search context. Start with your resume, complete
            your profile, and then use that context across companies, jobs, applications, and follow-ups.
          </p>
        </div>
        <ul className="focus-list">
          <li>Save your profile once and keep improving it</li>
          <li>Keep company and job-search filters consistent</li>
          <li>Capture the materials you actually sent</li>
          <li>Use AI as an assistant, not as an autopilot</li>
        </ul>
      </section>

      <section className="public-alpha-band" aria-labelledby="workflow-title">
        <div>
          <p className="eyebrow">What JobOps does</p>
          <h2 id="workflow-title">It connects the pieces of a serious technical job search.</h2>
          <p>
            Job seekers are often told to follow specific companies, check them regularly for relevant roles, tailor
            their materials, and track every application. You can do that with spreadsheets, saved links, notes, and
            separate AI chats — but it is easy to miss details or lose track of what happened.
          </p>
          <p>
            JobOps brings those pieces into one workspace: your profile, target companies, saved jobs, drafted
            materials, application history, and natural-language updates.
          </p>
        </div>
        <ul className="focus-list">
          {workflowItems.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>

      <section className="public-alpha-band alpha-status-band" aria-labelledby="alpha-status-title">
        <div>
          <p className="eyebrow">Alpha status</p>
          <h2 id="alpha-status-title">The first product slice is taking shape.</h2>
          <p>
            JobOps is early alpha software, not a finished SaaS product. The current build focuses on the foundation:
            request access, log in, save job-search context, and build toward AI-assisted application workflows that
            remember what you already saved.
          </p>
        </div>
        <div className="alpha-status-columns">
          <div>
            <h3>Available now</h3>
            <ul>
              {availableNowItems.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>Coming next</h3>
            <ul>
              {comingNextItems.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="public-alpha-band metrics-band" aria-labelledby="public-metrics-title">
        <div>
          <p className="eyebrow">Public metrics</p>
          <h2 id="public-metrics-title">
            {hasLiveMetric(metrics) ? "Early alpha snapshot." : "Alpha metrics are coming online."}
          </h2>
          <p>
            As the alpha develops, this page will show safe aggregate activity such as users onboarded, companies
            tracked, jobs saved, applications tracked, and AI-assisted materials drafted.
          </p>
          <p>
            Private job-search details, saved materials, notes, and application history should never appear here.
          </p>
        </div>
        <dl className="public-metrics-grid">
          {metrics.map((item) => (
            <div key={item.id}>
              <dt>{item.label}</dt>
              <dd className={displayMetricValue(item.value) === "Coming soon" ? "coming-soon" : undefined}>
                {displayMetricValue(item.value)}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="public-alpha-band access-band" id="alpha-access" aria-labelledby="alpha-access-title">
        <div>
          <p className="eyebrow">Request access</p>
          <h2 id="alpha-access-title">Want to try JobOps as an early alpha user?</h2>
          <p>
            I’m looking for technical professionals who want a more organized way to use AI while managing companies,
            jobs, applications, materials, and follow-ups.
          </p>
          <p>
            Share your name, email, and a quick note about your job-search workflow.
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

function hasLiveMetric(metrics: PublicJobOpsMetric[]) {
  return metrics.some((item) => typeof item.value === "number" && item.value > 0);
}

function displayMetricValue(value: PublicJobOpsMetric["value"]) {
  if (typeof value !== "number" || value <= 0) {
    return "Coming soon";
  }

  return value.toLocaleString();
}
