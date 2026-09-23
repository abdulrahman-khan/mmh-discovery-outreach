"""Verbatim-match checks: corpus-URL aware for URLs, normalised for emails/phones."""
from mmh_discovery.extractor.verbatim import contains_exact, contains_normalized, contains_url


def test_exact_match_for_urls():
    hay = 'click <a href="https://example.com/contact">here</a>'
    assert contains_exact("https://example.com/contact", hay)
    assert not contains_exact("https://example.com/contact-us", hay)


def test_url_match_ignores_query_and_trailing_slash():
    hay = '<a href="https://twitter.com/ist_team?lang=en">x</a>'
    assert contains_url("https://twitter.com/ist_team", hay)
    assert contains_url("https://twitter.com/ist_team?lang=en", hay)
    assert contains_url("https://twitter.com/ist_team/", hay)
    # but never invents a handle that is not in the corpus
    assert not contains_url("https://twitter.com/other_team", hay)


def test_url_match_decodes_entities():
    hay = '<a href="https://www.youtube.com/embed/videoseries?si=x&amp;list=PL123">v</a>'
    assert contains_url("https://www.youtube.com/embed/videoseries?si=x&list=PL123", hay)
    assert contains_url("https://www.youtube.com/embed/videoseries", hay)


def test_email_plain_and_mailto():
    page = '<a href="mailto:info@masjid.example.org">info</a>'
    assert contains_normalized("info@masjid.example.org", page)
    assert contains_normalized("mailto:info@masjid.example.org", page)


def test_phone_with_separators():
    page = "Call us at (905) 555-1234 today"
    assert contains_normalized("905-555-1234", page)
    assert contains_normalized("905.555.1234", page)
    assert contains_normalized("905 555 1234", page)
    # a country-code-formatted needle only matches if the digits exist in the page
    assert not contains_normalized("+19055551234", page)
    assert contains_normalized("+19055551234", "tel:+19055551234")
    assert not contains_normalized("9055559999", page)


def test_case_insensitive():
    assert contains_normalized("INFO@MASJID.EXAMPLE.ORG", "write to info@masjid.example.org")


def test_empty_needle_never_matches():
    assert not contains_normalized("", "anything")
