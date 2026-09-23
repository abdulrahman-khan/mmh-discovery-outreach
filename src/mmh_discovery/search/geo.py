"""Geo derivation tables for the search pipeline.

Same FSA-first-letter map and curated city table as scripts/backfill_province.py
(that script predates the package; the tables are small, stable, and copied
rather than imported across the scripts/src boundary).
"""
from __future__ import annotations

VALID_PROVINCES = {"ON", "QC", "BC", "AB", "SK", "MB", "NS", "NB", "NL", "PE",
                   "NT", "YT", "NU"}

# Canada Post FSA first letter -> province/territory ('B' is NS, NB is 'E').
FSA_FIRST_LETTER = {"A": "NS", "B": "NS", "C": "SK", "E": "NB", "G": "QC",
                    "H": "QC", "J": "QC", "K": "ON", "L": "ON", "M": "ON",
                    "N": "ON", "P": "ON", "R": "MB", "S": "SK", "T": "AB",
                    "V": "BC", "Y": "NT"}

# Curated city -> province for cities observed in this dataset.
CITY_PROVINCE = {
    "mississauga": "ON", "toronto": "ON", "scarborough": "ON", "etobicoke": "ON",
    "thornhill": "ON", "oakville": "ON", "waterloo": "ON", "cambridge": "ON",
    "london": "ON", "sarnia": "ON", "brampton": "ON", "hamilton": "ON",
    "ottawa": "ON", "cornwall": "ON", "gatineau": "QC", "saint-laurent": "QC",
    "richmond": "BC", "vancouver": "BC", "burnaby": "BC", "surrey": "BC",
    "calgary": "AB", "lloydminster": "SK",
}


def province_from_fsa(fsa: str | None) -> str | None:
    if not fsa:
        return None
    prov = FSA_FIRST_LETTER.get(fsa.strip().upper()[:1])
    return prov if prov in VALID_PROVINCES else None
