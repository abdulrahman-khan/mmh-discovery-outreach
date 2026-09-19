-- Masjid directory schema. Applied with `make migrate` or psql directly.

create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

create table if not exists sources (
  id text primary key,
  label text not null,
  trust smallint not null default 50,
  enabled boolean not null default true
);

insert into sources (id, label, trust) values
  ('manual',    'Manual entry',       100),
  ('cra',       'CRA charities list',  90),
  ('directory', 'Curated directory',   70),
  ('web',       'Masjid website',      60),
  ('osm',       'OpenStreetMap',       50),
  ('overture',  'Overture Maps',       40),
  ('search',    'Web search',          30)
on conflict (id) do nothing;

create table if not exists source_records (
  id uuid primary key default gen_random_uuid(),
  source_id text not null references sources(id),
  external_id text,
  url text,
  fetched_at timestamptz not null default now(),
  http_status smallint,
  content_hash text,
  storage_path text,
  meta jsonb not null default '{}'
);
create index if not exists source_records_source_url_idx on source_records (source_id, url);

create table if not exists organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  alt_names text[] not null default '{}',
  slug text unique,
  status text not null default 'needs_review'
    check (status in ('active', 'needs_review', 'inactive', 'merged')),
  website text,
  phone text,
  email text,
  address_line1 text,
  city text,
  province text check (province is null or length(province) = 2),
  postal_code text,
  lat double precision,
  lng double precision,
  province_source text check (province_source in ('addr_tag', 'bbox', 'manual')),
  social jsonb not null default '{}',
  confidence smallint,
  verified_at timestamptz,
  verified_by text,
  notes text,
  merged_into uuid references organizations(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists organizations_name_trgm_idx on organizations using gin (name gin_trgm_ops);
create index if not exists organizations_province_idx on organizations (province);

create table if not exists contacts (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  kind text not null check (kind in ('email', 'phone', 'social', 'contact_form', 'address')),
  value text not null,
  label text,
  is_primary boolean not null default false,
  valid boolean,
  invalid boolean not null default false,
  verification jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, kind, value)
);
create index if not exists contacts_kind_idx on contacts (kind);

-- Latest known origin of each org/field. Upsert on conflict; history lives in source_records.
create table if not exists field_provenance (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null check (entity_type in ('org', 'contact')),
  entity_id uuid not null,
  field text not null,
  source_record_id uuid references source_records(id),
  method text not null,
  confidence smallint,
  verified boolean not null default false,
  created_at timestamptz not null default now(),
  unique (entity_type, entity_id, field)
);

-- Per-source rows before entity resolution. resolved_org_id null = unresolved.
create table if not exists org_candidates (
  id uuid primary key default gen_random_uuid(),
  source_id text not null references sources(id),
  external_id text not null,
  name text,
  alt_name text,
  phone text,
  email text,
  website text,
  address_line1 text,
  city text,
  province text,
  postal_code text,
  lat double precision,
  lng double precision,
  social jsonb not null default '{}',
  raw jsonb not null,
  run_id text,
  resolved_org_id uuid references organizations(id),
  created_at timestamptz not null default now(),
  unique (source_id, external_id)
);
create index if not exists org_candidates_unresolved_idx
  on org_candidates (source_id) where resolved_org_id is null;

-- One row per URL ever fetched. Drives dedupe + staggered re-crawl windows.
create table if not exists crawl_ledger (
  url_hash text primary key,
  url text not null,
  domain text,
  org_id uuid references organizations(id),
  status text not null,
  http_status smallint,
  fail_reason text,
  fetched_at timestamptz not null default now(),
  next_eligible_at timestamptz,
  run_id text
);
create index if not exists crawl_ledger_domain_idx on crawl_ledger (domain);

create table if not exists crawl_jobs (
  id uuid primary key default gen_random_uuid(),
  url text not null,
  domain text,
  org_id uuid references organizations(id),
  reason text not null default 'discover'
    check (reason in ('discover', 'contact_page', 'stale_refresh', 'manual')),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'done', 'failed', 'skipped')),
  attempts smallint not null default 0,
  fail_category text,
  fail_reason text,
  queued_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  next_attempt_at timestamptz,
  run_id text,
  unique (url, reason)
);
create index if not exists crawl_jobs_due_idx on crawl_jobs (status, next_attempt_at);

create table if not exists extraction_runs (
  id uuid primary key default gen_random_uuid(),
  run_id text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  pages_seen int not null default 0,
  orgs_created int not null default 0,
  orgs_updated int not null default 0,
  rejected int not null default 0,
  llm_cost_usd numeric(10,4),
  error text
);

create table if not exists campaigns (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  channel text not null default 'email'
    check (channel in ('email', 'phone', 'social', 'in_person', 'mail')),
  is_commercial boolean not null default false,
  status text not null default 'draft'
    check (status in ('draft', 'approved', 'sending', 'done', 'cancelled')),
  created_at timestamptz not null default now()
);

create table if not exists outreach_activities (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations(id) on delete cascade,
  campaign_id uuid references campaigns(id),
  channel text not null,
  direction text not null default 'outbound'
    check (direction in ('outbound', 'inbound')),
  status text not null default 'sent'
    check (status in ('queued', 'sent', 'replied', 'no_answer', 'opt_out', 'bounced', 'done')),
  note text,
  performed_by text,
  performed_at timestamptz not null default now()
);
create index if not exists outreach_org_idx on outreach_activities (org_id, performed_at desc);

create table if not exists saved_lists (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  filters jsonb not null default '{}',
  org_ids uuid[] not null default '{}',
  owner text,
  created_at timestamptz not null default now()
);

-- Never contact these, regardless of campaign type.
create table if not exists suppression (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('email', 'phone', 'domain', 'org')),
  value text not null,
  reason text,
  created_at timestamptz not null default now(),
  unique (kind, value)
);

create table if not exists app_profiles (
  auth_user_id uuid primary key,
  email text,
  role text not null default 'viewer' check (role in ('viewer', 'editor', 'admin'))
);
