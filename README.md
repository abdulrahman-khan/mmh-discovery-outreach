# mmh-discovery-outreach

Discovers Canadian masjids and builds an outreach-ready contact directory for Muslim Media Hub: who they are, where they are, and how to reach them - every contact traceable to the page it came from.

## Data

![How the data was built](docs/images/mmh-client-data-overview.png)

## Data Collection Pipeline

![Search pipeline architecture](docs/images/search-pipeline-architecture.png)

## Report confidence levels

The Search Leads report splits recovered contacts into two tabs. The split is about **evidence**, not guesswork:

**Confirmed** - the organisation itself published the value:

- Email on the organisation's own domain (or on a page the organisation owns)
- Phone or postal code published on the organisation's own pages
- City that matches our Canadian city and postal records

**Needs review** - someone else published the value, so a person should judge it:

- Email or phone found on a third-party page (social media, business directories, charity registries) - it may be current, stale, or belong to a similarly named organisation
- City or province mentioned in a search snippet with nothing to corroborate it
- City not found in our postal records, or without a matching province

How to use Needs review rows: click the source link shown on each row and check the page says what the report says it says. Confirmed rows were already applied to the main directory; Needs review rows never are, by design.

## Data compliance

- CASL / PIPEDA: business contact information is collected from public pages only; confirm the contact before the first send.
- robots.txt respected on every crawl; rate limits honored.
- No Google Places data and no Meta scraping - both are ToS violations and never used as sources.
- No raw page snapshots retained; every stored value keeps provenance (source URL + fetch record).
