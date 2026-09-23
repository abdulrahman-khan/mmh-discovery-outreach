"""Verify prospects_template.html page JS under node with a stub document.

Extracts <script>, injects a synthetic __DATA__, runs assertions for tab
switching, counts, escaping, paging stat, and search. Same convention as
build_report.py's node verification. Usage: python scripts/check_prospects_js.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "prospects_template.html"

DATA = [
    {"o": "Alpha Masjid", "f": "Email", "v": "info@alpha.ca",
     "u": "https://alpha.ca/contact", "h": "alpha.ca",
     "l": "confirmed", "w": "Email on the organisation's own domain", "a": True},
    {"o": "Beta Centre", "f": "Phone", "v": "416-555-0100",
     "u": "https://fb.com/beta", "h": "fb.com",
     "l": "review", "w": "Phone found on a third-party page", "a": False},
    {"o": "Gamma \"Quote\" & <Tag>", "f": "City", "v": "Ottawa",
     "u": "", "h": "gamma.ca", "l": "confirmed",
     "w": "City matches our Canadian city records", "a": False},
]

STUB = """
const els = {};
function el(id){ if(!els[id]) els[id] = {innerHTML:"", textContent:"",
  value:(id==="per"?"25":""), classList:{toggle(){}}, disabled:false,
  onclick:null, oninput:null, onchange:null}; return els[id]; }
globalThis.document = { getElementById: el, querySelectorAll: () => [] };
"""

TESTS = """
const body = els["body"].innerHTML;
if (!body.includes("Alpha Masjid")) throw new Error("confirmed row missing");
if (body.includes("Beta Centre")) throw new Error("review row leaked into confirmed tab");
if (els_["n-ok"].textContent !== 2) throw new Error("n-ok wrong");
if (els_["n-rev"].textContent !== 1) throw new Error("n-rev wrong");
if (!body.includes("Gamma") || !body.includes("&amp;")) throw new Error("escape wrong");
if (!body.includes("already in the main directory")) throw new Error("applied note missing");
if (els_["stat"].textContent !== "1\\u20132 of 2") throw new Error("stat wrong: " + els_["stat"].textContent);
els_["tab-rev"].onclick();
const rev = els_["body"].innerHTML;
if (!rev.includes("Beta Centre") || rev.includes("Alpha Masjid")) throw new Error("review tab wrong");
if (els_["stat"].textContent !== "1\\u20131 of 1") throw new Error("review stat wrong");
els_["tab-ok"].onclick();
els_["q"].value = "alpha"; els_["q"].oninput();
if (!els_["body"].innerHTML.includes("Alpha")) throw new Error("search broken");
els_["q"].value = "zzz"; els_["q"].oninput();
if (els_["body"].innerHTML !== "") throw new Error("empty search should clear body");
console.log("JS OK: tabs, counts, escaping, applied note, paging, search all pass");
"""


def main() -> int:
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__STATS__", "3 leads")
            .replace("__DATE__", "September 22, 2026")
            .replace("__DATA__", json.dumps(DATA, ensure_ascii=False)))
    js = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    src = STUB.replace("els_ = els", "") + js + "\n" + TESTS.replace("els_", "els")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(src)
        path = f.name
    return subprocess.run([sys.executable and "node", path]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
