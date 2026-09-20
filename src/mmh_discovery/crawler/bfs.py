"""BFS scope rules and link extraction.

Scope: a seed authorises its apex domain and every subdomain of it
(example.com -> sub.example.com, never notexample.com). Shared-platform hosts
crawl only the exact seed page. Blocklisted hosts are skipped entirely.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

from selectolax.lexbor import LexborHTMLParser

from mmh_discovery import config
from mmh_discovery.core.naming import domain_from_url

# Extensions that are never crawlable pages (files, feeds, media).
_NON_HTML_EXTENSIONS = frozenset(
    {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".gz",
        ".rar", ".7z", ".exe", ".dmg", ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".svg", ".ico", ".css", ".js", ".mp3", ".mp4", ".avi", ".mov", ".mkv",
        ".woff", ".woff2", ".ttf", ".eot", ".rss", ".atom", ".xml", ".json",
    }
)


def canonicalise_seed(url: str) -> str:
    """Normalise a seed URL: scheme defaults to https, drop fragment,
    keep exactly one trailing slash on a bare-origin URL."""
    url = url.strip()
    if not urlparse(url).scheme:
        url = "https://" + url
    parts = urlparse(url)
    cleaned = parts._replace(fragment="")
    out = urlunparse(cleaned)
    if cleaned.path in ("", "/") and not cleaned.query:
        out = f"{cleaned.scheme}://{cleaned.netloc}/"
    return out


def _apex(domain: str) -> str:
    """Approximate apex: last two labels (sufficient for .ca/.com masjids;
    no public-suffix DB needed at this scale)."""
    labels = domain.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else domain


def same_scope(seed_url: str, candidate_url: str) -> bool:
    """True if candidate's host is the seed's apex domain or a subdomain of it."""
    seed_host = domain_from_url(seed_url)
    cand_host = domain_from_url(candidate_url)
    if not seed_host or not cand_host:
        return False
    seed_apex = _apex(seed_host)
    return cand_host == seed_apex or cand_host.endswith("." + seed_apex)


def is_blocked(url: str) -> bool:
    host = domain_from_url(url)
    return any(host == d or host.endswith("." + d) for d in config.BLOCKED_DOMAINS)


def is_shared_platform(url: str) -> bool:
    host = domain_from_url(url)
    return any(host == d or host.endswith("." + d) for d in config.SHARED_PLATFORM_HOSTS)


def is_crawlable(url: str) -> bool:
    """http(s) URL whose path is not an obvious non-HTML file."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    path = parsed.path.lower()
    return not any(path.endswith(ext) for ext in _NON_HTML_EXTENSIONS)


def extract_links(base_url: str, html: str) -> list[str]:
    """Absolute, deduplicated, same-page-only links from anchor hrefs.
    Order preserved; mailto/tel/javascript and fragments are dropped."""
    parser = LexborHTMLParser(html)
    seen: set[str] = set()
    out: list[str] = []
    for node in parser.css("a[href]"):
        href = node.attributes.get("href") or ""
        href = href.strip()
        if href.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ("http", "https"):
            continue
        cleaned = urlunparse(parsed._replace(fragment=""))
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out
