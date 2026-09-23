-- Search pipeline: per-field enrichment proposals (Tavily search pass).
-- Proposals-first: nothing reaches organizations/org_candidates from search
-- unless vetting marked it 'verified' AND --apply was passed.
-- vetting: proposed (human review needed) | verified (auto-apply eligible) |
--          rejected (kept for audit, never applied)
-- status:    open (awaiting apply/review) | applied | dismissed

create table if not exists enrichment_proposals (
  id uuid primary key default gen_random_uuid(),
  run_id text not null,
  org_id uuid references organizations(id),
  candidate_id uuid references org_candidates(id),
  domain text,
  field text not null check (field in
    ('email', 'phone', 'city', 'province', 'postal_code', 'website')),
  proposed_value text not null,
  source_url text,
  evidence text,
  vetting text not null default 'proposed'
    check (vetting in ('proposed', 'verified', 'rejected')),
  vet_rule text,
  status text not null default 'open'
    check (status in ('open', 'applied', 'dismissed')),
  created_at timestamptz not null default now(),
  applied_at timestamptz,
  unique nulls not distinct (org_id, candidate_id, field, proposed_value)
);
create index if not exists enrichment_proposals_review_idx
  on enrichment_proposals (status, vetting);
create index if not exists enrichment_proposals_org_idx
  on enrichment_proposals (org_id);
