"use client";

import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";

export type TrackedCompany = {
  id: string;
  company_id?: string;
  name: string;
  normalized_name: string | null;
  domain?: string | null;
  website_url: string | null;
  careers_url: string | null;
  job_listings_url: string | null;
  greenhouse_board_token?: string | null;
  ashby_board_url?: string | null;
  lever_slug?: string | null;
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
  data_confidence?: string | null;
  provider_grounding_metadata_summary?: Record<string, unknown>;
  discovery_query: string | null;
  search_queries_used: string[];
  discovered_by: string | null;
  derivation_status: string;
  review_status: string;
  notes: string;
  added_at?: string;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
  last_checked_at: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  active_job_count?: number;
  saved_job_count?: number;
  application_count?: number;
  open_application_count?: number;
  can_sync_jobs?: boolean;
  sync_providers?: string[];
};

export function CompaniesList({
  apiBasePath = "/api",
  initialCompanies = [],
  workspaceBasePath = ""
}: {
  apiBasePath?: string;
  initialCompanies?: TrackedCompany[];
  workspaceBasePath?: string;
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
              <CompanyCard company={company} key={company.id} workspaceBasePath={workspaceBasePath} />
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

export function CompanyCard({ company, workspaceBasePath = "" }: { company: TrackedCompany; workspaceBasePath?: string }) {
  const detailHref = `${workspaceBasePath}/companies/${company.id}`;
  const websiteUrl = safeExternalUrl(company.website_url);
  const careersUrl = safeExternalUrl(company.careers_url);
  const jobListingsUrl = safeExternalUrl(company.job_listings_url);
  const providerMetadata = company.provider_grounding_metadata_summary || {};

  return (
    <article className="company-card">
      <div className="company-card-main">
        <div className="company-card-header">
          <div>
            <h2>{company.name}</h2>
            <p>{company.domain || company.normalized_name || "Tracked company"}</p>
          </div>
          <div className="job-card-badges" aria-label={`${company.name} company status`}>
            {company.archived_at ? <span className="application-status application-status-archived">Archived</span> : null}
            {company.can_sync_jobs ? <span className="application-status application-status-highlight">Sync-ready</span> : null}
          </div>
        </div>

        <dl className="company-provider-metadata">
          <MetadataBox label="Website" value={displayUrlHost(websiteUrl) || company.domain || "Unknown"} />
          <MetadataBox label="Careers" value={displayUrlHost(careersUrl) || "Unknown"} />
          <MetadataBox label="Job board" value={displayUrlHost(jobListingsUrl) || "Unknown"} />
          <MetadataBox label="Greenhouse" value={company.greenhouse_board_token || "None"} />
          <MetadataBox label="Ashby" value={displayUrlHost(safeExternalUrl(company.ashby_board_url)) || "None"} />
          <MetadataBox label="Lever" value={company.lever_slug || "None"} />
          <MetadataBox label="Headquarters" value={formatHeadquarters(company)} />
          <MetadataBox label="Remote policy" value={formatStatus(company.remote_policy)} />
          <MetadataBox label="Jobs" value={formatCount(company.active_job_count, "active")} />
          <MetadataBox label="Saved" value={formatCount(company.saved_job_count, "saved")} />
          <MetadataBox label="Applications" value={formatCount(company.application_count, "application")} />
          <MetadataBox label="Open apps" value={formatCount(company.open_application_count, "open")} />
        </dl>

        <div className="company-card-content">
          <section className="job-info-panel company-description-panel" aria-label={`${company.name} company description`}>
            <h3>Company Description</h3>
            <div className="job-scroll-text company-scroll-text">
              {company.description ? preserveText(company.description) : <p>No description available.</p>}
            </div>
          </section>
          {company.fit_reason || company.source_summary ? (
            <section className="job-info-panel company-fit-panel" aria-label={`${company.name} fit and source notes`}>
              <h3>Fit / Source Notes</h3>
              <div className="job-scroll-text company-scroll-text">
                {company.fit_reason ? <p>{company.fit_reason}</p> : null}
                {company.source_summary ? <p>{company.source_summary}</p> : null}
              </div>
            </section>
          ) : null}
          <TagRow label="Role fit" values={company.role_fit_tags} />
          <TagRow label="Mission fit" values={company.mission_fit_tags} />
          <TagRow label="Hiring locations" values={company.hiring_locations} />
          <TagRow label="Technologies" values={metadataList(providerMetadata.technologyNames || providerMetadata.technologySlugs)} />
          <TagRow label="Keywords" values={metadataList(providerMetadata.keywordSlugs)} />
        </div>
      </div>

      <aside className="company-card-rail" aria-label={`${company.name} details`}>
        <div className="record-rail-section company-card-meta">
          <dl className="company-details record-detail-grid">
            <DetailItem label="Added" value={formatDate(company.added_at || company.created_at)} />
            <DetailItem label="First seen" value={formatDate(company.first_seen_at || company.created_at)} />
            <DetailItem label="Last seen" value={formatDate(company.last_seen_at)} />
            <DetailItem label="Last checked" value={formatDate(company.last_checked_at)} />
            <DetailItem label="Status" value={formatStatus(company.review_status)} />
            <DetailItem label="Derived" value={formatStatus(company.derivation_status)} />
            <DetailItem label="Confidence" value={formatStatus(company.data_confidence || "unknown")} />
            <DetailItem label="Discovered by" value={company.discovered_by || "Unknown"} />
            <DetailItem label="Source URLs" value={`${safeSourceUrls(company.source_urls).length}`} />
          </dl>
        </div>

        <div className="company-links company-card-actions" aria-label={`${company.name} actions`}>
          <Link href={detailHref}>View Company</Link>
          <ExternalLink href={websiteUrl} label="Visit Website" />
          <ExternalLink href={careersUrl} label="Careers" />
          <ExternalLink href={jobListingsUrl} label="Jobs" />
          <SourceLinks urls={company.source_urls} />
        </div>
      </aside>
    </article>
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
  const safeUrls = safeSourceUrls(urls);
  if (safeUrls.length === 0) {
    return null;
  }

  return (
    <details className="company-source-links">
      <summary>Sources ({safeUrls.length})</summary>
      <div>
        {safeUrls.map((url, index) => (
          <ExternalLink href={url} key={`${url}-${index}`} label={`Source ${index + 1}`} />
        ))}
      </div>
    </details>
  );
}

function ExternalLink({ href, label }: { href: string | null | undefined; label: string }) {
  const safeHref = safeExternalUrl(href);
  if (!safeHref) {
    return null;
  }

  return (
    <a href={safeHref} rel="noopener noreferrer" target="_blank">
      {label}
    </a>
  );
}

function MetadataBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="job-primary-metadata-item">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
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

function formatHeadquarters(company: TrackedCompany) {
  const values = [company.headquarters_city, company.headquarters_country].filter(Boolean);
  return values.length > 0 ? values.join(", ") : "Unknown";
}

export function formatStatus(value?: string | null) {
  return (value || "unknown").replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

export function formatDate(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

export function safeExternalUrl(value?: string | null) {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function safeSourceUrls(urls: string[]) {
  return urls.map((url) => safeExternalUrl(url)).filter((url): url is string => Boolean(url));
}

function displayUrlHost(value?: string | null) {
  if (!value) {
    return null;
  }
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function formatCount(value: number | undefined, label: string) {
  return `${value ?? 0} ${label}`;
}

function metadataList(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).slice(0, 8);
}

function preserveText(value: string) {
  const paragraphs = value
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (paragraphs.length === 0) {
    return <p>{value}</p>;
  }
  return paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>);
}
