"""Agent enrichment pass for the manual-entry queue (D-003: never fight the WAF).

Instead of crawling the blocked site, search Tavily (same API path as the tsw
scholarship discovery pipeline, per D-004) and extract emails/phones/postal
codes/city hints from result titles, URLs and content snippets.
Writes proposals to data/enrichment_proposals.json; nothing touches the DB here.

Keys: TAVILY_API_KEYS in .env, comma-separated. 429 waits and rotates to the
next key; a key returning 432 (quota exhausted) is dropped for the run.
"""
import itertools
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import psycopg
from mmh_discovery import config

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")
FSA_RE = re.compile(r"\b([A-PR-Wa-pr-w]\d[A-PR-Za-pr-w])\s?\d[A-PR-Za-pr-w]\d\b")
CITY_PROV_RE = re.compile(r"\b([A-Z][A-Za-z'.\- ]{2,28}?),\s*(ON|BC|AB|SK|MB|QC|NS|NB|NL|PE|YT|NT|NU)\b")

BAD_EMAIL_SUBS = ("example.", "sentry", "wixpress", ".png", ".jpg", ".gif", ".webp", ".css", ".js",
                  "yourdomain", "domain.com", "email.com", "sentry.io", "@2x", "no-reply", "noreply",
                  "@duckduckgo.com", "@google.com", "wixpress.com")


class KeyPool:
    """Rotating Tavily keys: 429 rotates, 432 drops the key."""

    def __init__(self, keys: list[str]):
        self.keys = list(keys)
        self.cycle = itertools.cycle(self.keys)
        self.dropped = set()

    def search(self, query: str) -> list[dict]:
        payload = json.dumps({
            "query": query, "topic": "general", "search_depth": "basic",
            "max_results": 8, "include_answer": False, "include_raw_content": False,
        }).encode()
        for _ in range(4 * len(self.keys)):
            key = next(self.cycle)
            if key in self.dropped:
                continue
            req = urllib.request.Request(
                TAVILY_SEARCH_URL, data=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = json.loads(r.read().decode())
                time.sleep(1.1)
                return data.get("results", [])
            except urllib.error.HTTPError as e:
                if e.code == 429:  # rate limit: back off, rotate to next key
                    print(f"    429 on key ...{key[-6:]}, rotating")
                    time.sleep(3)
                elif e.code == 432:  # quota exhausted for this key
                    print(f"    key ...{key[-6:]} out of credits (432), dropping")
                    self.dropped.add(key)
                    if len(self.dropped) == 1:
                        raise SystemExit(f"All key attempts failed; first key is out of credits. "
                                         f"Add more keys to TAVILY_API_KEYS.")
                else:
                    print(f"    tavily HTTP {e.code}: {e.read()[:200]!r}")
                    time.sleep(2)
            except Exception as e:  # noqa: BLE001
                print(f"    tavily error {e}")
                time.sleep(2)
        return []


def extract(text: str) -> dict:
    out = {"email": None, "phone": None, "fsa": None, "city_prov": None}
    emails = [e.lower() for e in EMAIL_RE.findall(text)]
    emails = [e for e in emails if not any(b in e for b in BAD_EMAIL_SUBS)
              and not re.search(r"\.(png|jpe?g|gif|webp|css|js|svg)$", e)]
    if emails:
        # prefer info@/admin@/contact@/office@ style addresses
        emails.sort(key=lambda e: (e.split("@")[0] not in
                                   ("info", "admin", "contact", "office", "masjid", "administrator", "secretary"), len(e)))
        out["email"] = emails[0]
    m = PHONE_RE.search(text)
    if m:
        out["phone"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = FSA_RE.search(text)
    if m:
        out["fsa"] = m.group(1).upper()
    m = CITY_PROV_RE.search(text)
    if m and len(m.group(1).strip()) > 2:
        out["city_prov"] = (m.group(1).strip().title(), m.group(2))
    return out


def main():
    keys = config.TAVILY_API_KEYS
    if not keys:
        raise SystemExit("TAVILY_API_KEYS not set in .env - create keys at https://app.tavily.com "
                         "(free tier: 1000 credits/key/month) and add them comma-separated.")
    pool = KeyPool(keys)
    print(f"{len(keys)} Tavily key(s) in pool")

    with psycopg.connect(config.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                select domain, url, org_id, name, org_email, org_phone,
                       candidate_email, candidate_phone, address_line1, city, province
                from manual_entry_queue
                where coalesce(org_email, candidate_email) is null
                   or coalesce(org_phone, candidate_phone) is null
                   or coalesce(province, '') = ''
                order by domain""")
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    print(f"queue rows needing enrichment: {len(rows)}")

    proposals = []
    for i, row in enumerate(rows, 1):
        dom = row["domain"]
        name = (row["name"] or dom).strip()
        site = re.sub(r"^https?://(www\.)?", "", row["url"] or f"https://{dom}").strip("/")
        queries = [f"{site} contact email phone",
                   f'"{name}" mosque contact']
        found = {"email": None, "phone": None, "fsa": None, "city_prov": None}
        for q in queries:
            if found["email"] and found["phone"] and found["city_prov"]:
                break
            for r in pool.search(q):
                text = " ".join(str(r.get(k) or "") for k in ("title", "url", "content"))
                got = extract(text)
                for k, v in got.items():
                    if v and not found[k]:
                        found[k] = v
        prop = {
            "domain": dom, "org_id": str(row["org_id"]), "name": name,
            "have_email": bool(row["org_email"] or row["candidate_email"]),
            "have_phone": bool(row["org_phone"] or row["candidate_phone"]),
            "have_province": bool(row["province"]),
            "found_email": found["email"], "found_phone": found["phone"],
            "found_fsa": found["fsa"], "found_city": (found["city_prov"] or (None, None))[0],
            "found_province": (found["city_prov"] or (None, None))[1],
        }
        proposals.append(prop)
        status = " ".join(f"{k}={v}" for k, v in found.items() if v) or "nothing"
        print(f"[{i}/{len(rows)}] {dom}: {status}")

    Path("data/enrichment_proposals.json").write_text(
        json.dumps(proposals, indent=1, ensure_ascii=False), encoding="utf-8")
    n_e = sum(1 for p in proposals if p["found_email"] and not p["have_email"])
    n_p = sum(1 for p in proposals if p["found_phone"] and not p["have_phone"])
    n_pv = sum(1 for p in proposals if p["found_province"] and not p["have_province"])
    print(f"proposals: +{n_e} emails, +{n_p} phones, +{n_pv} provinces -> data/enrichment_proposals.json")


if __name__ == "__main__":
    main()
