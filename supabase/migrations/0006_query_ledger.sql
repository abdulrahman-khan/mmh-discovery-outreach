-- Search pipeline: cross-run query ledger (DEVNOTES/RESEARCH-search-scrape-architectures.md §6.3).
-- Novelty by construction: a (target, template) query slot is searched at most once
-- per freshness window, across ALL runs. "New queries every run" becomes an
-- iteration problem, not a generation problem.

create table if not exists public.search_query_ledger (
  query_hash    text primary key,          -- same key as the response cache
  query         text not null,
  target_domain text,
  template      text,                      -- which slot in the (target x template) space
  results_count int,
  run_id        text not null,
  searched_at   timestamptz not null default now()
);

create index if not exists search_query_ledger_target_idx
  on public.search_query_ledger (target_domain, searched_at);
