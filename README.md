# mmh-discovery-outreach

Discovers and enriches masjid (mosque) contact data across Canada into Supabase
for Muslim Media Hub outreach.

## Pipeline

OSM / CRA / directories -> `org_candidates` (staging) -> entity resolution ->
`organizations` + `contacts` with `field_provenance`.
Websites are crawled politely (honest UA, robots.txt, 1 req/s per domain), up
to 10 pages per domain via BFS. One LLM call per domain (DGX vLLM,
OpenAI-compatible) extracts every distinct email/phone/social/contact form plus
raw context excerpts; values are verbatim-checked against the fetched HTML
before anything is written. No raw HTML is stored anywhere: `source_records` is
an audit log of URL/status/content-hash per (URL, run), and per-domain token
metrics land in `data/runs/{run_id}/extract.jsonl`.

## Hard bans

- Google Places / Maps data: ToS forbids storing business names or addresses
  outside Google services. Never a source.
- Scraping Facebook/Instagram/Meta: ToS violation. Social URLs are only read
  off masjid websites, never crawled.

## Compliance

- CASL: campaigns are classified by `campaigns.is_commercial`. Commercial CEMs
  require express/implied consent, identification, and unsubscribe; addresses
  harvested at scale are presumed non-consentable, so commercial sends require
  a manual verification gate first.
- PIPEDA: no raw HTML snapshots are retained (decision D-013). Contact data
  lives only in `contacts` with provenance; crawl artifacts are metrics-only.

## Setup

See `STARTUP.md` for the full walkthrough. TL;DR:

```
make setup             # uv sync (venv + all extras)
copy .env.example .env # fill DATABASE_URL
make migrate           # apply supabase/migrations
make seed-jobs         # queue crawl jobs from candidate websites
make crawl-once        # crawl + LLM-extract + persist one batch
make test
```
