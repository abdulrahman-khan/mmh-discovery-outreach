# mmh-discovery-outreach

Discovers and enriches masjid (mosque) contact data across Canada into Supabase
for Muslim Media Hub outreach.

## Pipeline

OSM / CRA / directories -> `org_candidates` (staging) -> entity resolution ->
`organizations` + `contacts` with `field_provenance`. Websites are crawled
politely (honest UA, robots.txt, 1 req/s per domain); raw HTML is stored in
Supabase Storage with a row in `source_records`.

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
- PIPEDA: raw snapshots are retained indefinitely by current design. This is
  documented debt; add a retention job before scaling past MVP.

## Setup

See `STARTUP.md` for the full walkthrough. TL;DR:

```
make setup             # venv + install
copy .env.example .env # fill DATABASE_URL
make migrate           # apply supabase/migrations/0001_init.sql
make osm-import        # dry-run OSM discovery (writes data/runs/)
make test
```
