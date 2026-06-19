"use client";

import Link from "next/link";
import React, { useEffect, useMemo, useState } from "react";

export type CompanyBucketId = "watch" | "avoid" | "archived";

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
  discoverySource?: string | null;
  discoverySourceLabel?: string | null;
  dataOriginSource?: string | null;
  dataOriginSourceType?: string | null;
  dataOriginSourceLabel?: string | null;
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

const companyBuckets: Array<{ id: CompanyBucketId; label: string }> = [
  { id: "watch", label: "Watch list" },
  { id: "avoid", label: "Avoid list" },
  { id: "archived", label: "Archived" }
];

const companyEmptyStates: Record<CompanyBucketId, { title: string; copy: string }> = {
  watch: {
    title: "No watched companies yet",
    copy: "Companies you follow or save will appear here."
  },
  avoid: {
    title: "No avoided companies",
    copy: "Companies you mark as avoid will appear here."
  },
  archived: {
    title: "No archived companies",
    copy: "Archived companies are hidden from active company discovery but preserved here."
  }
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
  const [messageKind, setMessageKind] = useState<"success" | "error" | "info">("info");
  const [activeBucket, setActiveBucket] = useState<CompanyBucketId>(() => defaultCompanyBucket(initialCompanies));
  const [pendingCompanyAction, setPendingCompanyAction] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadCompanies() {
      try {
        const response = await fetch(`${apiBasePath}/companies`, { cache: "no-store" });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          if (active) {
            setMessageKind("error");
            setMessage(apiErrorMessage(payload, response.status));
          }
          return;
        }
        if (!Array.isArray(payload)) {
          if (active) {
            setMessageKind("error");
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
          setMessageKind("error");
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

  const companyCounts = useMemo(() => buildCompanyBucketCounts(companies), [companies]);
  useEffect(() => {
    if (companyCounts[activeBucket] > 0 || companies.length === 0) {
      return;
    }
    setActiveBucket(defaultCompanyBucket(companies));
  }, [activeBucket, companies, companyCounts]);

  const sortedCompanies = useMemo(
    () =>
      [...companies]
        .filter((company) => companyBucket(company) === activeBucket)
        .sort((left, right) => (right.added_at || right.created_at).localeCompare(left.added_at || left.created_at)),
    [activeBucket, companies]
  );
  const activeEmptyState = companyEmptyStates[activeBucket];

  async function runCompanyAction(company: TrackedCompany, action: "archive" | "restore" | "avoid" | "watch") {
    setPendingCompanyAction(`${company.id}:${action}`);
    setMessage("");
    try {
      const response = await fetch(`${apiBasePath}/companies/${company.id}/${action}`, {
        method: "POST"
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload || typeof payload !== "object" || !("company" in payload)) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      const updatedCompany = payload.company as TrackedCompany;
      setCompanies((current) => current.map((item) => (item.id === updatedCompany.id ? updatedCompany : item)));
      setMessageKind("success");
      setMessage(typeof payload.message === "string" ? payload.message : "Company updated.");
      window.dispatchEvent(new CustomEvent("jobops:companies-updated"));
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : "Company action failed.");
    } finally {
      setPendingCompanyAction(null);
    }
  }

  return (
    <main className="dashboard-main company-workspace">
      <section className="page-heading">
        <p className="eyebrow">Company watchlist</p>
        <h1>Companies</h1>
        <p>Review model-derived companies to follow for future roles, with source links kept close for verification.</p>
      </section>

      {message ? <p className={messageKind === "error" ? "application-error" : "application-message"}>{message}</p> : null}

      <section className="company-list" aria-labelledby="company-list-title">
        <div className="application-list-header">
          <div>
            <p className="eyebrow">Watchlist</p>
            <h2 id="company-list-title">Saved companies</h2>
          </div>
          <span>{companyCounts[activeBucket]}</span>
        </div>

        <div className="queue-tabs" role="tablist" aria-label="Company list filters">
          {companyBuckets.map((tab) => (
            <button
              aria-selected={activeBucket === tab.id}
              className={`queue-tab${activeBucket === tab.id ? " active" : ""}`}
              key={tab.id}
              onClick={() => setActiveBucket(tab.id)}
              role="tab"
              type="button"
            >
              <span>{tab.label}</span>
              <strong>{companyCounts[tab.id]}</strong>
            </button>
          ))}
        </div>

        {sortedCompanies.length > 0 ? (
          <div className="company-card-grid">
            {sortedCompanies.map((company) => (
              <CompanyCard
                company={company}
                key={company.id}
                onCompanyAction={runCompanyAction}
                pendingAction={pendingCompanyAction}
                workspaceBasePath={workspaceBasePath}
              />
            ))}
          </div>
        ) : (
          <div className="empty-state-block">
            <h2>{activeEmptyState.title}</h2>
            <p>{activeEmptyState.copy}</p>
          </div>
        )}
      </section>
    </main>
  );
}

export function CompanyCard({
  company,
  onCompanyAction,
  pendingAction,
  workspaceBasePath = ""
}: {
  company: TrackedCompany;
  onCompanyAction?: (company: TrackedCompany, action: "archive" | "restore" | "avoid" | "watch") => void;
  pendingAction?: string | null;
  workspaceBasePath?: string;
}) {
  const detailHref = `${workspaceBasePath}/companies/${company.id}`;
  const websiteUrl = safeExternalUrl(company.website_url);
  const careersUrl = safeExternalUrl(company.careers_url);
  const companySiteUrl = websiteUrl || websiteUrlFromDomain(company.domain);
  const providerMetadata = company.provider_grounding_metadata_summary || {};
  const atsInferred = inferredAtsProviders(company, providerMetadata);

  return (
    <article className="company-card">
      <div className="company-card-main">
        <div className="company-card-header">
          <div>
            <h2>
              <Link className="company-card-title-link" href={detailHref}>
                {company.name}
              </Link>
            </h2>
            {companySiteUrl ? (
              <a className="company-card-site-link" href={companySiteUrl} rel="noopener noreferrer" target="_blank">
                {displayUrlHost(companySiteUrl) || company.domain || companySiteUrl}
              </a>
            ) : null}
          </div>
          <div className="job-card-badges" aria-label={`${company.name} company status`}>
            {company.archived_at ? <span className="application-status application-status-archived">Archived</span> : null}
            {company.can_sync_jobs ? <span className="application-status application-status-highlight">Sync-ready</span> : null}
          </div>
        </div>

        <div className="company-provider-metadata">
          <CompanyCounts company={company} />
          <dl className="company-provider-facts">
            <MetadataBox label="Headquarters" value={companyHeadquartersValue(company)} />
            <MetadataBox label={<ProviderIcon label="Greenhouse" mark="GH" provider="greenhouse" />} value={company.greenhouse_board_token} />
            <MetadataBox label={<ProviderIcon label="Ashby" mark="A" provider="ashby" />} value={displayUrlHost(safeExternalUrl(company.ashby_board_url))} />
            <MetadataBox label={<ProviderIcon label="Lever" mark="L" provider="lever" />} value={company.lever_slug} />
          </dl>
        </div>

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
        <details className="record-rail-section company-card-meta">
          <summary>Metadata</summary>
          <dl className="company-details record-detail-grid">
            <DetailItem label="Added" value={formatDate(company.added_at || company.created_at)} />
            <DetailItem label="First seen" value={formatDate(company.first_seen_at || company.created_at)} />
            <DetailItem label="Last seen" value={formatDate(company.last_seen_at)} />
            <DetailItem label="Last checked" value={formatDate(company.last_checked_at)} />
            <DetailItem label="Status" value={formatStatus(company.review_status)} />
            <DetailItem label="Derived" value={formatStatus(company.derivation_status)} />
            <DetailItem label="Confidence" value={formatStatus(company.data_confidence || "unknown")} />
            <DetailItem label="Discovery source" value={formatDiscoverySource(company)} />
            <DetailItem label="Data source" value={formatDataSource(company)} />
            <DetailItem label="Discovered by" value={company.discovered_by || "Unknown"} />
            {atsInferred ? <DetailItem label="ATS inferred" value={atsInferred} /> : null}
            <DetailItem label="Source URLs" value={`${safeSourceUrls(company.source_urls).length}`} />
          </dl>
        </details>

        <div className="company-links company-card-actions" aria-label={`${company.name} actions`}>
          {onCompanyAction ? (
            <>
              {company.archived_at ? (
                <button
                  className="secondary-action compact-action"
                  disabled={pendingAction === `${company.id}:restore`}
                  onClick={() => onCompanyAction(company, "restore")}
                  type="button"
                >
                  {pendingAction === `${company.id}:restore` ? "Restoring..." : "Restore"}
                </button>
              ) : (
                <button
                  className="secondary-action compact-action"
                  disabled={pendingAction === `${company.id}:archive`}
                  onClick={() => onCompanyAction(company, "archive")}
                  type="button"
                >
                  {pendingAction === `${company.id}:archive` ? "Archiving..." : "Archive"}
                </button>
              )}
              {companyBucket(company) === "avoid" ? (
                <button
                  className="secondary-action compact-action"
                  disabled={pendingAction === `${company.id}:watch`}
                  onClick={() => onCompanyAction(company, "watch")}
                  type="button"
                >
                  {pendingAction === `${company.id}:watch` ? "Saving..." : "Watch"}
                </button>
              ) : !company.archived_at ? (
                <button
                  className="secondary-action compact-action"
                  disabled={pendingAction === `${company.id}:avoid`}
                  onClick={() => onCompanyAction(company, "avoid")}
                  type="button"
                >
                  {pendingAction === `${company.id}:avoid` ? "Saving..." : "Mark Avoid"}
                </button>
              ) : null}
            </>
          ) : null}
          <ExternalLink href={websiteUrl} label="Visit Website" />
          <ExternalLink href={careersUrl} label="Careers" />
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

export function companyBucket(company: TrackedCompany): CompanyBucketId {
  if (company.archived_at) {
    return "archived";
  }
  if (isAvoidedCompany(company)) {
    return "avoid";
  }
  return "watch";
}

export function buildCompanyBucketCounts(companies: TrackedCompany[]): Record<CompanyBucketId, number> {
  return companies.reduce(
    (counts, company) => {
      counts[companyBucket(company)] += 1;
      return counts;
    },
    { watch: 0, avoid: 0, archived: 0 }
  );
}

export function defaultCompanyBucket(companies: TrackedCompany[]): CompanyBucketId {
  const counts = buildCompanyBucketCounts(companies);
  if (counts.watch > 0 || companies.length === 0) {
    return "watch";
  }
  if (counts.avoid > 0) {
    return "avoid";
  }
  return "archived";
}

function isAvoidedCompany(company: TrackedCompany) {
  const status = (company.review_status || "").trim().toLowerCase().replace(/-/g, "_");
  return ["avoid", "avoided", "do_not_target", "do_not_pursue", "rejected"].includes(status);
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

function CompanyCounts({ company }: { company: TrackedCompany }) {
  return (
    <section className="company-count-panel" aria-label={`${company.name} jobs and applications`}>
      <h3>Jobs</h3>
      <dl>
        <div>
          <dd>{company.active_job_count ?? 0}</dd>
          <dt>active</dt>
        </div>
        <div>
          <dd>{company.saved_job_count ?? 0}</dd>
          <dt>saved</dt>
        </div>
        <div>
          <dd>{company.application_count ?? 0}</dd>
          <dt>applied</dt>
        </div>
        <div>
          <dd>{company.open_application_count ?? 0}</dd>
          <dt>open</dt>
        </div>
      </dl>
    </section>
  );
}

function companyHeadquartersValue(company: TrackedCompany) {
  const value = formatHeadquarters(company);
  return value === "Unknown" ? null : value;
}

function ProviderIcon({ label, mark, provider }: { label: string; mark: string; provider: "greenhouse" | "ashby" | "lever" }) {
  return (
    <span
      aria-label={label}
      className={`company-provider-icon company-provider-icon-${provider}`}
      role="img"
      title={label}
    >
      {mark}
    </span>
  );
}

function MetadataBox({ label, value }: { label: React.ReactNode; value?: string | null }) {
  if (!value) {
    return null;
  }

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

function websiteUrlFromDomain(value: string | null | undefined) {
  const cleaned = (value || "").trim();
  if (!cleaned || /\s/.test(cleaned) || cleaned.includes("/")) {
    return null;
  }
  return safeExternalUrl(`https://${cleaned}`);
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

function metadataList(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0).slice(0, 8);
}

function formatDataSource(company: TrackedCompany) {
  if (company.dataOriginSourceLabel && company.dataOriginSource !== "unknown") {
    if (company.dataOriginSourceType && ["source_url", "website", "careers_url", "job_listings_url"].includes(company.dataOriginSourceType)) {
      return displayUrlHost(company.dataOriginSource) || company.dataOriginSourceLabel;
    }
    return company.dataOriginSourceLabel;
  }
  if (company.dataOriginSource && company.dataOriginSource !== "unknown") {
    return displayUrlHost(company.dataOriginSource) || formatStatus(company.dataOriginSource);
  }
  if (company.careers_url) {
    return displayUrlHost(company.careers_url) || "Company careers page";
  }
  if (company.job_listings_url) {
    return displayUrlHost(company.job_listings_url) || "Company job listings page";
  }
  if (company.website_url) {
    return displayUrlHost(company.website_url) || "Company website";
  }
  const firstSourceUrl = safeSourceUrls(company.source_urls)[0];
  if (firstSourceUrl) {
    return displayUrlHost(firstSourceUrl) || "Source URL";
  }
  return "Unknown";
}

function formatDiscoverySource(company: TrackedCompany) {
  if (company.discoverySourceLabel && company.discoverySource !== "unknown") {
    return company.discoverySourceLabel;
  }
  if (company.discoverySource && company.discoverySource !== "unknown") {
    return formatStatus(company.discoverySource);
  }
  const discoveredBy = (company.discovered_by || "").toLowerCase();
  if (discoveredBy === "theirstack") {
    return "TheirStack";
  }
  if (discoveredBy === "gemini") {
    return "Gemini model-grounded discovery";
  }
  if (discoveredBy || company.derivation_status === "model_derived") {
    return "Model-grounded discovery";
  }
  if (company.derivation_status === "user_entered") {
    return "User-entered";
  }
  return "Unknown";
}

function inferredAtsProviders(company: TrackedCompany, providerMetadata: Record<string, unknown>) {
  const providers = new Set<string>();
  if (company.greenhouse_board_token) {
    providers.add("Greenhouse");
  }
  if (company.ashby_board_url) {
    providers.add("Ashby");
  }
  if (company.lever_slug) {
    providers.add("Lever");
  }
  const atsInference = providerMetadata.atsInference;
  if (atsInference && typeof atsInference === "object" && !Array.isArray(atsInference)) {
    const row = atsInference as Record<string, unknown>;
    if (row.greenhouseBoardToken) {
      providers.add("Greenhouse");
    }
    if (row.ashbyBoardUrl) {
      providers.add("Ashby");
    }
    if (row.leverSlug) {
      providers.add("Lever");
    }
  }
  return providers.size ? Array.from(providers).join(", ") : null;
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
