-- Extract pipeline: raw_context column for LLM-summarizer input,
-- drop raw HTML snapshot storage (snapshots are no longer retained).

alter table organizations add column if not exists raw_context text;

comment on column organizations.raw_context is
  'Concatenated markdown excerpts extracted from the masjid website, each block prefixed with its source URL. Feeds the future story_summary summarizer pass.';

alter table source_records drop column if exists storage_path;

comment on table source_records is
  'Fetch audit log per URL. HTML bodies are not retained; content_hash + http_status + meta are enough for provenance and re-crawl decisions.';
