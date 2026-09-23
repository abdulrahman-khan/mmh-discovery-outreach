"""BFS scope rules: apex+subdomain scope, blocklist, shared platforms, links."""
from mmh_discovery.crawler.bfs import (
    canonicalise_seed,
    extract_links,
    is_blocked,
    is_crawlable,
    is_shared_platform,
    same_scope,
)


def test_same_scope_allows_apex_and_subdomains():
    seed = "https://example.com/"
    assert same_scope(seed, "https://example.com/about")
    assert same_scope(seed, "https://www.example.com/about")
    assert same_scope(seed, "https://sub.example.com/contact")
    assert same_scope(seed, "https://deep.sub.example.com/x")


def test_same_scope_rejects_other_domains():
    seed = "https://example.com/"
    assert not same_scope(seed, "https://notexample.com/")
    assert not same_scope(seed, "https://example.com.evil.org/")
    assert not same_scope(seed, "https://other.org/contact")


def test_subdomain_seed_covers_sibling_subdomains():
    # Seed on one subdomain still authorises the whole apex (decision 4).
    seed = "https://masjid.example.ca/"
    assert same_scope(seed, "https://news.example.ca/posts")


def test_is_blocked_matches_host_and_subdomain():
    assert is_blocked("https://moonode.com/masjid/123")
    assert is_blocked("https://www.facebook.com/somemosque")
    assert is_blocked("https://islaminfo.com/x")
    assert not is_blocked("https://example.com/x")


def test_is_shared_platform():
    assert is_shared_platform("https://centres.macnet.ca/centre/42")
    assert is_shared_platform("https://ahmadiyya.ca/local-masjid")
    assert not is_shared_platform("https://masjid.example.com/")


def test_is_crawlable_skips_files_and_bad_schemes():
    assert is_crawlable("https://example.com/contact")
    assert not is_crawlable("https://example.com/brochure.pdf")
    assert not is_crawlable("https://example.com/logo.PNG")
    assert not is_crawlable("ftp://example.com/x")


def test_canonicalise_seed():
    assert canonicalise_seed("example.com") == "https://example.com/"
    assert canonicalise_seed("http://example.com#top") == "http://example.com/"
    assert canonicalise_seed("https://example.com/a?b=1#c") == "https://example.com/a?b=1"


HTML = """
<html><body>
<a href="/about">About</a>
<a href="https://example.com/news/">News</a>
<a href="https://example.com/news/">News dup</a>
<a href="mailto:info@example.com">mail</a>
<a href="tel:+19055551234">tel</a>
<a href="#section">fragment only</a>
<a href="https://other.org/x">outside</a>
<a href="page.pdf">pdf</a>
</body></html>
"""


def test_extract_links_absolute_dedupe_and_filters():
    links = extract_links("https://example.com/", HTML)
    assert "https://example.com/about" in links
    assert "https://example.com/news/" in links
    assert links.count("https://example.com/news/") == 1
    assert not any(link.startswith("mailto:") or "info@example.com" in link for link in links)
    assert not any(link.endswith("#section") for link in links)
    # base-relative resolution keeps the host; outside links are still returned
    # (scope filtering is the caller's job via same_scope)
    assert "https://other.org/x" in links
