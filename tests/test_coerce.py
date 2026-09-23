"""Bare-string LLM items are coerced to {value, source_url} before validation."""
from mmh_discovery.extractor.extract import ExtractionError, _coerce_payload


def _pages():
    return [
        ("https://x.org/", "<html>home</html>"),
        ("https://x.org/contact", "<html><a href='https://fb.com/xorg'>f</a>"
         "<a href='https://a.co/c?v=1&amp;x=2'>form</a></html>"),
    ]


def test_bare_string_becomes_item_with_source_page():
    payload = {"contact_forms": ["https://a.co/c?v=1&x=2"]}
    out = _coerce_payload(payload, _pages())
    assert out["contact_forms"] == [
        {"value": "https://a.co/c?v=1&x=2", "source_url": "https://x.org/contact"}
    ]


def test_bare_social_gets_platform():
    payload = {"socials": ["https://fb.com/xorg"]}
    out = _coerce_payload(payload, _pages())
    assert out["socials"][0]["platform"] == "facebook"
    assert out["socials"][0]["source_url"] == "https://x.org/contact"


def test_bare_social_with_unknown_platform_dropped():
    payload = {"socials": ["https://example.com/weird"]}
    assert _coerce_payload(payload, _pages())["socials"] == []


def test_object_items_pass_through():
    item = {"value": "a@b.ca", "source_url": "https://x.org/"}
    out = _coerce_payload({"emails": [item]}, _pages())
    assert out["emails"] == [item]


def test_non_dict_payload_raises():
    try:
        _coerce_payload(["nope"], _pages())
    except ExtractionError:
        pass
    else:
        raise AssertionError("expected ExtractionError")
