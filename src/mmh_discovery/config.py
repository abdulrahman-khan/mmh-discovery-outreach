"""Pipeline tuning knobs. Secrets come from env; everything else is edited here."""
import os

DATABASE_URL: str = os.getenv("DATABASE_URL", "")

OVERPASS_URL: str = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_TIMEOUT_SECONDS: int = 180

# Honest bot UA; masjid sites are the client's own community, no fingerprint spoofing.
USER_AGENT: str = (
    "MuslimMediaHubDirectoryBot/1.0 (+contact: admin@muslimmediahub.com)"
)

REQUEST_TIMEOUT_SECONDS: int = 15
MIN_CONTENT_BYTES: int = 500
MAX_CONTENT_CHARS: int = 15000
MAX_RETRIES: int = 2
RETRY_BACKOFF_BASE: float = 1.5
PER_DOMAIN_MIN_INTERVAL_SECONDS: float = 1.0

RESCRAPE_DAYS: int = 180
RESCRAPE_STAGGER_DAYS: int = 60
RETRY_COOLDOWN_DAYS: int = 3
