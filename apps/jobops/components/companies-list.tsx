"use client";

import React, { useEffect, useMemo, useState } from "react";

export type TrackedCompany = {
  id: string;
  company_id?: string;
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
  added_at?: string;
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
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          if (active) {
            setMessage(apiErrorMessage(payload, response.status));
          }
          return;
        }
        if (!Array.isArray(payload)) {
          if (active) {
            setMessage("Company API returned an unexpected response.");
          }
          return;
        }
        if (active) {
          setMessage("");
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
    () => [...companies].sort((left, right) => (right.added_at || right.created_at).localeCompare(left.added_at || left.created_at)),
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
                <div className="company-card-main">
                  <div className="company-card-header">
                    <h2>{company.name}</h2>
                    <FoldedText className="company-description" value={company.description || company.fit_reason || "No description saved yet."} />
                  </div>

                  {company.fit_reason && company.description ? <FoldedText className="company-fit" value={company.fit_reason} /> : null}
                  <FoldedText className="company-source-summary" value={company.source_summary} />
                </div>

                <aside className="company-card-rail" aria-label={`${company.name} details`}>
                  <div className="record-rail-section">
                    <dl className="company-details record-detail-grid">
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
                    <TagRow label="Role fit" values={company.role_fit_tags} />
                    <TagRow label="Mission fit" values={company.mission_fit_tags} />
                  </div>

                  <div className="record-rail-section">
                    <dl className="company-details record-detail-grid">
                      <div>
                        <dt>Added</dt>
                        <dd>{formatDate(company.added_at || company.created_at)}</dd>
                      </div>
                      <div>
                        <dt>Status</dt>
                        <dd>{formatStatus(company.review_status)}</dd>
                      </div>
                      <div>
                        <dt>Derived</dt>
                        <dd>{formatStatus(company.derivation_status)}</dd>
                      </div>
                      <div>
                        <dt>Discovered by</dt>
                        <dd>{company.discovered_by || "Unknown"}</dd>
                      </div>
                    </dl>
                  </div>

                  <div className="company-links" aria-label={`${company.name} links`}>
                    <ExternalLink href={company.website_url} label="Website" />
                    <ExternalLink href={company.careers_url} label="Careers" />
                    <ExternalLink href={company.job_listings_url} label="Jobs" />
                    <SourceLinks urls={company.source_urls} />
                  </div>
                </aside>
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

function apiErrorMessage(payload: unknown, status: number) {
  if (payload && typeof payload === "object" && "error" in payload && typeof payload.error === "string") {
    return payload.error;
  }
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return `Company API request failed with HTTP ${status}.`;
}

function SourceLinks({ urls }: { urls: string[] }) {
  if (urls.length === 0) {
    return null;
  }

  return (
    <details className="company-source-links">
      <summary>Sources ({urls.length})</summary>
      <div>
        {urls.map((url, index) => (
          <ExternalLink href={url} key={`${url}-${index}`} label={`Source ${index + 1}`} />
        ))}
      </div>
    </details>
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

function TagRow({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className="company-tag-row" aria-label={label}>
      <span className="company-tag-label">{label}</span>
      {values.map((value) => (
        <span key={value}>{value}</span>
      ))}
    </div>
  );
}

function FoldedText({ value, className }: { value?: string | null; className: string }) {
  if (!value) {
    return null;
  }
  const preview = previewText(value);
  if (preview === value) {
    return <p className={className}>{value}</p>;
  }
  return (
    <details className={`folded-text ${className}`}>
      <summary>{preview}</summary>
      <p>{value}</p>
    </details>
  );
}

function previewText(value: string) {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= 145) {
    return compact;
  }
  return `${compact.slice(0, 145).trimEnd()}...`;
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

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}
