"""Pipeline tuning knobs. Secrets come from env; everything else is edited here."""
import os

from dotenv import load_dotenv

load_dotenv()


def _csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [v.strip().lower() for v in raw.split(",") if v.strip()]


DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# Tavily search keys (free tier, 1000 credits each). Comma-separated for rotation.
# Not _csv_env: keys are case-sensitive.
TAVILY_API_KEYS: list[str] = [v.strip() for v in os.getenv("TAVILY_API_KEYS", "").split(",")
                              if v.strip()]

OVERPASS_URL: str = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_TIMEOUT_SECONDS: int = 180

# Honest bot UA; masjid sites are the client's own community, no fingerprint spoofing.
USER_AGENT: str = (
    "MuslimMediaHubDirectoryBot/1.0 (+contact: admin@muslimmediahub.com)"
)

# HTTP fetch knobs.
REQUEST_TIMEOUT_SECONDS: int = 15
MIN_CONTENT_BYTES: int = 500
MAX_CONTENT_CHARS: int = 15000
MAX_RETRIES: int = 2
RETRY_BACKOFF_BASE: float = 1.5
PER_DOMAIN_MIN_INTERVAL_SECONDS: float = 1.0
RETRY_COOLDOWN_DAYS: int = 3

# BFS scope: how many pages to pull per domain before stopping.
CRAWLER_MAX_PAGES_PER_DOMAIN: int = 10

# Prompt context budget. Concatenated page HTML is truncated to this many chars
# before hitting the LLM. Measured on real masjid HTML: ~9.3 chars/token, so
# 350k chars ~= 38k prompt tokens - safe against the 131072-token window
# (max_model_len) with room for reasoning + response.
EXTRACT_HTML_CAP_CHARS: int = 350_000

# Served context window of the DGX model (vLLM max_model_len). Requests are
# sized so prompt + completion fit inside it.
LLM_MAX_MODEL_LEN: int = int(os.getenv("LLM_MAX_MODEL_LEN", "131072"))

# Domains that publish their masjid page on a shared platform (macnet, ahmadiyya, etc.).
# Crawl that page only, no BFS beyond it.
SHARED_PLATFORM_HOSTS: set[str] = {
    "centres.macnet.ca",
    "macnet.ca",
    "ahmadiyya.ca",
    "ahmadiyya.org",
}

# Hosts we never crawl (aggregators, docs hosts, Meta properties). Skip at seed time.
BLOCKED_DOMAINS: set[str] = {
    "moonode.com",
    "islaminfo.com",
    "google.com",
    "docs.google.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "wa.me",
    "whatsapp.com",
    "linkedin.com",
    "yellowpages.ca",
    "yelp.ca",
}

# Comma-separated domains that skip robots.txt enforcement. Add only after manual review.
ROBOTS_ALLOWLIST: set[str] = set(_csv_env("ROBOTS_ALLOWLIST"))

# LLM (vLLM on DGX, OpenAI-compatible).
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://100.76.204.90:8000/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "dgx-current")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")  # optional; DGX vLLM currently keyless
LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "600"))
LLM_MAX_CONCURRENCY: int = int(os.getenv("LLM_MAX_CONCURRENCY", "2"))
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "8192"))
# Qwen on vLLM is a thinking model: reasoning tokens eat max_tokens and can
# leave content=None. Extraction wants the JSON only, so thinking is off.
LLM_ENABLE_THINKING: bool = os.getenv("LLM_ENABLE_THINKING", "0") == "1"

# Local run artifacts (JSONL metrics, OSM candidate dumps). Never committed.
DATA_DIR: str = os.getenv("DATA_DIR", "data")
