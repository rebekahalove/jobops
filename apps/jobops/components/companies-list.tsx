"use client";

import React, { useEffect, useMemo, useState } from "react";

export type TrackedCompany = {
  id: string;
  name: string;
  normalized_name: string | null;
  website_url: string | null;
  careers_url: string | null;
  job_listings_url: string | null;
  description: string | null;
  headquarters_city: string | null;
  headquarters_country: string | null;
  operating_countries: string[];
  hiring_locations: string[];
  remote_policy: string;
  role_fit_tags: string[];
  mission_fit_tags: string[];
  fit_reason: string | null;
  source_urls: string[];
  source_summary: string | null;
  discovery_query: string | null;
  search_queries_used: string[];
  discovered_by: string | null;
  derivation_status: string;
  review_status: string;
  notes: string;
  created_at: string;
  updated_at: string;
  last_checked_at: string | null;
};

export function CompaniesList({
  apiBasePath = "/api",
  initialCompanies = []
}: {
  apiBasePath?: string;
  initialCompanies?: TrackedCompany[];
}) {
  const [companies, setCompanies] = useState(initialCompanies);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;

    async function loadCompanies() {
      try {
        const response = await fetch(`${apiBasePath}/companies`, { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as TrackedCompany[];
        if (active) {
          setCompanies(payload);
        }
      } catch {
        if (active) {
          setMessage("Company API is unavailable. Start FastAPI to load saved records.");
        }
      }
    }

    loadCompanies();
    window.addEventListener("jobops:companies-updated", loadCompanies);
    return () => {
      active = false;
      window.removeEventListener("jobops:companies-updated", loadCompanies);
    };
  }, [apiBasePath]);

  const sortedCompanies = useMemo(
    () => [...companies].sort((left, right) => right.created_at.localeCompare(left.created_at)),
    [companies]
  );

  return (
    <main className="dashboard-main company-workspace">
      <section className="page-heading">
        <p className="eyebrow">Company watchlist</p>
        <h1>Companies</h1>
        <p>Review model-derived companies to follow for future roles, with source links kept close for verification.</p>
      </section>

      {message ? <p className="application-message">{message}</p> : null}

      <section className="company-list" aria-labelledby="company-list-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Watchlist</p>
            <h2 id="company-list-title">Saved companies</h2>
          </div>
          <span>{companies.length}</span>
        </div>

        {sortedCompanies.length > 0 ? (
          <div className="company-card-grid">
            {sortedCompanies.map((company) => (
              <article className="company-card" key={company.id}>
                <div className="company-card-header">
                  <div>
                    <h2>{company.name}</h2>
                    <p>{company.description || company.fit_reason || "No description saved yet."}</p>
                  </div>
                  <div className="company-badges" aria-label={`${company.name} status`}>
                    <span>{formatStatus(company.review_status)}</span>
                    <span>{formatStatus(company.derivation_status)}</span>
                  </div>
                </div>

                {company.fit_reason && company.description ? <p className="company-fit">{company.fit_reason}</p> : null}

                <dl className="company-details">
                  <div>
                    <dt>Headquarters</dt>
                    <dd>{formatHeadquarters(company)}</dd>
                  </div>
                  <div>
                    <dt>Hiring locations</dt>
                    <dd>{formatList(company.hiring_locations)}</dd>
                  </div>
                  <div>
                    <dt>Remote policy</dt>
                    <dd>{formatStatus(company.remote_policy)}</dd>
                  </div>
                </dl>

                <TagRow values={company.role_fit_tags} />
                <TagRow values={company.mission_fit_tags} />

                <div className="company-links" aria-label={`${company.name} links`}>
                  <ExternalLink href={company.website_url} label="Website" />
                  <ExternalLink href={company.careers_url} label="Careers" />
                  <ExternalLink href={company.job_listings_url} label="Jobs" />
                  {company.source_urls.map((url, index) => (
                    <ExternalLink href={url} key={`${url}-${index}`} label={`Source ${index + 1}`} />
                  ))}
                </div>

                {company.source_summary ? <p className="company-source-summary">{company.source_summary}</p> : null}
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state-block">
            <h2>No companies yet</h2>
            <p>Ask the AI Command Center to discover companies to follow. New model-derived records will appear here for review.</p>
          </div>
        )}
      </section>
    </main>
  );
}

function ExternalLink({ href, label }: { href: string | null; label: string }) {
  if (!href) {
    return null;
  }

  return (
    <a href={href} rel="noopener noreferrer" target="_blank">
      {label}
    </a>
  );
}

function TagRow({ values }: { values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className="company-tag-row">
      {values.map((value) => (
        <span key={value}>{value}</span>
      ))}
    </div>
  );
}

function formatHeadquarters(company: TrackedCompany) {
  const values = [company.headquarters_city, company.headquarters_country].filter(Boolean);
  return values.length > 0 ? values.join(", ") : "Unknown";
}

function formatList(values: string[]) {
  return values.length > 0 ? values.join(", ") : "Unknown";
}

function formatStatus(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}
