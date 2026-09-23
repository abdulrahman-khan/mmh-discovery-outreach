"""Query templates, hit filtering/scoring, regex extraction, vetting rules."""
import httpx

from mmh_discovery.search.cache import query_key
from mmh_discovery.search.client import TavilyKeyPool
from mmh_discovery.search.extract import clean_emails, extract_fields, first_phone
from mmh_discovery.search.queries import (
    SearchTarget,
    build_queries,
    build_query_slots,
)
from mmh_discovery.search.scoring import filter_hits, is_blacklisted, quality_score_hit
from mmh_discovery.search.vetting import PROPOSED, VERIFIED, vet, vet_city_prov


def target(**kw):
    base = dict(org_id="o1", candidate_id=None, domain="peemosque.ca",
                name="Pee Mosque", website="https://peemosque.ca",
                city="Toronto", missing=("email", "phone"))
    base.update(kw)
    return SearchTarget(**base)


# --- queries

def test_query_slots_tag_templates():
    slots = build_query_slots(target())
    assert [t for t, _ in slots] == ["site_contact", "name_contact", "name_city"]
    assert slots[0][1] == "peemosque.ca contact email phone"


# --- query ledger gate (novelty by construction, DEVNOTES research §6.3)

def test_ledger_skips_fresh_slots_but_searches_new_ones():
    from mmh_discovery.search.run import run_search

    asked = []

    def handler(req):
        asked.append(req.content.decode())
        return httpx.Response(200, json={"results": []})

    pool = TavilyKeyPool(["k"], sleep=lambda s: None,
                         transport=httpx.MockTransport(handler))
    t = target()  # 3 slots: site_contact, name_contact, name_city
    site_q = build_queries(t)[0]
    # slot fresh in ledger, no cache hit -> skipped; the rest are searched
    run_search(pool, t, set(), {}, ledger=frozenset({query_key(site_q)}),
               ledger_entries=None, freshness_days=90)
    assert len(asked) == 2
    assert site_q not in "".join(asked)
    pool.close()


def test_ledger_ignored_when_freshness_zero():
    from mmh_discovery.search.run import run_search

    asked = []

    def handler(req):
        asked.append(1)
        return httpx.Response(200, json={"results": []})

    pool = TavilyKeyPool(["k"], sleep=lambda s: None,
                         transport=httpx.MockTransport(handler))
    t = target()
    all_hashes = {query_key(q) for q in build_queries(t)}
    run_search(pool, t, set(), {}, ledger=frozenset(all_hashes),
               ledger_entries=None, freshness_days=0)
    assert len(asked) == 3  # freshness 0 => ledger ignored entirely
    pool.close()


def test_queries_site_first_and_cap_at_three():
    qs = build_queries(target())
    assert qs[0] == "peemosque.ca contact email phone"
    assert '"Pee Mosque" mosque contact' in qs
    assert len(qs) <= 3


def test_queries_no_site_no_domain():
    t = target(domain=None, website=None, city=None)
    qs = build_queries(t)
    assert qs == ['"Pee Mosque" mosque contact', '"Pee Mosque" mosque Canada']


# --- scoring / filtering

def test_blacklist_blocks_meta_and_aggregators():
    assert is_blacklisted("https://www.facebook.com/masjid")
    assert is_blacklisted("https://x.placeweb.site/123")
    assert is_blacklisted("https://toronto.yellowpages.ca/bus/xxx")
    assert not is_blacklisted("https://masjidalnoor.ca/contact")


def test_contact_page_outranks_news_page():
    contact = quality_score_hit(url="https://a.ca/contact", title="Contact Us",
                                content="email info@a.ca")
    news = quality_score_hit(url="https://a.ca/news/eid-2024", title="Eid news",
                             content="blog post")
    assert contact > news


def test_filter_hits_dedupe_cap_and_score():
    seen: set[str] = set()
    counts: dict[str, int] = {}
    hits = [{"url": f"https://a.ca/p{i}", "title": "Masjid contact email",
             "content": "info@a.ca"} for i in range(5)]
    hits.append({"url": "https://facebook.com/x", "title": "Masjid", "content": ""})
    hits.append({"url": "https://a.ca/p0", "title": "dup", "content": "contact"})
    acc = filter_hits(hits, seen_urls=seen, domain_counts=counts)
    assert len(acc) == 3  # domain cap
    assert all("facebook" not in h["url"] for h in acc)
    acc2 = filter_hits(hits, seen_urls=seen, domain_counts=counts)
    assert acc2 == []  # caps and seen-urls persist across queries


# --- extraction

def test_clean_emails_runon_tld_not_swallowed():
    # sweep 1 regression: snippets glue text without spaces ("...gmail.comemail...")
    got = clean_emails("reach us at masjid.iqaluit@gmail.comemail or 5 info@x.ca")
    assert "masjid.iqaluit@gmail.com" in got
    assert all("comemail" not in e for e in got)


def test_clean_emails_multi_tld_survives():
    assert clean_emails("a:b@mosque.co.uk")[0] == "b@mosque.co.uk"


def test_emails_prefer_info_and_drop_junk():
    text = "build jquery@3.7.1 noreply@a.ca wixpress stuff admin@masjid.ca info@masjid.ca"
    assert clean_emails(text) == ["info@masjid.ca", "admin@masjid.ca"]


def test_phone_skips_us_area_code():
    assert first_phone("call 212-555-1234 or 416-555-9876") == "416-555-9876"
    assert first_phone("no numbers here") is None


def test_extract_fields_city_prov_and_fsa():
    hit = {"title": "Masjid Noor", "url": "https://masjidnoor.ca/contact",
           "content": "info@masjidnoor.ca 416-555-1234, M2N 7J8, Toronto, ON"}
    f = extract_fields(hit)
    assert f["emails"][0] == "info@masjidnoor.ca"
    assert f["phone"] == "416-555-1234"
    assert f["fsa"] == "M2N"
    assert (f["city"], f["province"]) == ("Toronto", "ON")


# --- vetting

def test_email_domain_match_verified_third_party_proposed():
    v, rule = vet("email", "info@peemosque.ca", "https://peemosque.ca/contact",
                  website="https://peemosque.ca")
    assert (v, rule) == (VERIFIED, "email_domain_match")
    v2, rule2 = vet("email", "info@aggregator.com", "https://aggregator.com/list",
                    website="https://peemosque.ca")
    assert (v2, rule2) == (PROPOSED, "email_third_party")


def test_email_on_own_page_even_other_domain_verified():
    v, rule = vet("email", "hello@peemosque.org", "https://peemosque.ca/contact",
                  domain="peemosque.ca")
    assert (v, rule) == (VERIFIED, "email_on_own_page")


def test_phone_and_province_rules():
    assert vet("phone", "416-555-1234", "https://peemosque.ca/c",
               domain="peemosque.ca")[0] == VERIFIED
    assert vet("phone", "416-555-1234", "https://elsewhere.ca/c",
               domain="peemosque.ca")[0] == PROPOSED
    assert vet("province", "ON", "https://peemosque.ca/c", domain="peemosque.ca")[0] \
        == VERIFIED


def test_city_prov_pair_only_when_table_agrees():
    table = {"toronto": "ON"}
    assert vet_city_prov("Toronto", "ON", city_ok=table)[0] == VERIFIED
    assert vet_city_prov("Springfield", "ON", city_ok=table)[0] == PROPOSED
    assert vet_city_prov("Oakville", "BC", city_ok=table)[0] == PROPOSED
