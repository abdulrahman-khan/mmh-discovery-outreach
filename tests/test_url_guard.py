from mmh_discovery.core.url_guard import is_safe_public_url


def test_rejects_empty():
    assert is_safe_public_url("")[0] is False


def test_rejects_bad_scheme():
    ok, reason = is_safe_public_url("ftp://example.com/file")
    assert ok is False
    assert "scheme" in reason


def test_rejects_localhost():
    assert is_safe_public_url("http://localhost/admin")[0] is False


def test_rejects_ip_literals():
    for url in (
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://[::1]/",
    ):
        assert is_safe_public_url(url)[0] is False, url


def test_rejects_no_host():
    assert is_safe_public_url("https:///path")[0] is False
