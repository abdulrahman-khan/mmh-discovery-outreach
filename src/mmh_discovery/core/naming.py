"""Filename and identity helpers shared by discovery, crawl, and storage layers."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse


def domain_from_url(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.").lower()


def short_hash(value: str, length: int = 8) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].rstrip("-")
