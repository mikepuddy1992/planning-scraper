"""
Planning Application Scraper
Targets: planit.org.uk API
Filter:  Residential developments of 5-30 dwellings
"""

import csv
import io
import re
import ssl
import urllib.request
from datetime import date, timedelta

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
MIN_DWELLINGS = 5
MAX_DWELLINGS = 30
DAYS_BACK     = 4      # Max the API supports is 4; use 1 for daily runs
PAGE_SIZE     = 1000

OUTPUT_COLUMNS = [
    "uid", "area_name", "description", "postcode", "address", "url",
    "app_size", "app_type", "app_state", "start_date",
    "other_fields.n_dwellings", "other_fields.agent_company",
    "other_fields.agent_name", "other_fields.agent_address",
    "other_fields.applicant_name", "other_fields.case_officer",
    "other_fields.decision",
]

# ─────────────────────────────────────────────
# DWELLING COUNT EXTRACTION
# Ordered from most-specific to least-specific.
# Each pattern MUST have the number as group 1.
# Anchored to words that mean "units of housing",
# NOT dimensions, heights, or other measurements.
# ─────────────────────────────────────────────
DWELLING_PATTERNS = [
    # "10 no. dwellings" / "7 dwellings" / "dwellinghouses"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?dwellings?(?:house)?',
    # "10no. residential units" / "10 residential plots"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?residential\s+(?:units?|plots?|homes?)',
    # "10 affordable homes" / "10 new homes"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+|affordable\s+)+homes?',
    # "10 self-contained flats" / "10 new flats" / "10 apartments"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?(?:self.contained\s+)?(?:flats?|apartments?)\b',
    # "erection of 10 houses" - but NOT "erection of 6 metre" or "6 storey"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?(?:detached|semi.detached|terraced|affordable|market)\s+(?:houses?|homes?|dwellings?)',
    # "for 5-7 dwellings" range — take upper number
    r'for\s+\d+[\-–]\s*(\d+)\s*dwellings?',
    # "erection of N" — only when followed by housing word, not dimensions
    r'erection\s+of\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|apartments?|residential)',
    # "construction of N dwellings/homes/flats"
    r'construction\s+of\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|apartments?|residential)',
    # "development of N dwellings/homes"
    r'development\s+of\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?)',
    # "into N dwellings" (conversions)
    r'into\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?dwellings?',
    # "provide N dwellings/homes/flats"
    r'provide\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|apartments?)',
]

# App types that are never new residential developments
EXCLUDED_APP_TYPES = {"trees", "telecoms", "advertising"}

# Description phrases that indicate it's NOT a new development
# (conditions, amendments, tree works etc.)
EXCLUDED_DESC_PHRASES = [
    "discharge of condition",
    "approval of details",
    "non-material amendment",
    "prior approval for works",
    "certificate of lawfulness",
    "works to a tree",
    "tree preservation",
    "advertisement consent",
    "listed building consent",
    "prior notification",
]


def extract_dwelling_count(row: dict) -> int | None:
    # 1. Direct field
    n_dw = row.get("other_fields.n_dwellings", "").strip()
    if n_dw:
        try:
            return int(float(n_dw))
        except ValueError:
            pass

    # 2. Regex on description
    desc = row.get("description", "")
    for pattern in DWELLING_PATTERNS:
        m = re.search(pattern, desc, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                pass
    return None


def is_relevant(row: dict) -> bool:
    app_type = row.get("app_type", "").lower()
    if app_type in EXCLUDED_APP_TYPES:
        return False
    desc = row.get("description", "").lower()
    if any(phrase in desc for phrase in EXCLUDED_DESC_PHRASES):
        return False
    return True


# ─────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────
def fetch(days_back: int, pg_sz: int) -> list[dict]:
    # The API caps 'recent' at 4 - silently clamp if higher value passed
    days_back = min(days_back, 4)
    url = (
        f"https://www.planit.org.uk/api/applics/csv"
        f"?compress=on&recent={days_back}&pg_sz={pg_sz}&max_recs={pg_sz}"
    )
    print(f"[→] Fetching: {url}")
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "text/csv,*/*",
        "Referer": "https://www.planit.org.uk/",
    })
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        raw = resp.read().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(raw)))
    print(f"[✓] Downloaded {len(rows)} applications")
    return rows


# ─────────────────────────────────────────────
# FILTER
# ─────────────────────────────────────────────
def filter_rows(rows, min_dw, max_dw):
    matched, skipped_irrelevant, skipped_no_count, skipped_range = [], 0, 0, 0
    for row in rows:
        if not is_relevant(row):
            skipped_irrelevant += 1
            continue
        count = extract_dwelling_count(row)
        if count is None:
            skipped_no_count += 1
            continue
        if min_dw <= count <= max_dw:
            row["_dwelling_count"] = count
            matched.append(row)
        else:
            skipped_range += 1

    print(f"[✓] {len(matched)} matched ({min_dw}–{max_dw} dwellings)")
    print(f"    {skipped_irrelevant} skipped (irrelevant type/conditions)")
    print(f"    {skipped_no_count} skipped (no dwelling count found)")
    print(f"    {skipped_range} skipped (outside size range)")
    return matched


# ─────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────
def write_csv(rows, filepath, columns):
    all_cols = ["_dwelling_count"] + columns
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[✓] Saved → {filepath}")


def print_summary(rows, min_dw, max_dw, days_back):
    print(f"\n{'='*70}")
    print(f"  PLANNING LEADS — {len(rows)} applications ({min_dw}–{max_dw} dwellings)")
    print(f"  Last {days_back} day(s)")
    print(f"{'='*70}")
    for r in rows:
        print(f"\n  [{r['_dwelling_count']} dwellings]  {r.get('uid','')}")
        print(f"  {r.get('address','')[:70]}")
        print(f"  {r.get('area_name','')}  |  {r.get('postcode','')}")
        print(f"  Agent: {r.get('other_fields.agent_company','')}  —  {r.get('other_fields.agent_name','')}")
        print(f"  Status: {r.get('app_state','')}  |  Type: {r.get('app_type','')}")
        print(f"  {r.get('description','')[:130]}")
        print(f"  {r.get('url','')}")
    print(f"\n{'='*70}\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n[Planning Scraper]  filter: {MIN_DWELLINGS}–{MAX_DWELLINGS} dwellings  |  last {DAYS_BACK} day(s)\n")
    all_rows = fetch(DAYS_BACK, PAGE_SIZE)
    matched  = filter_rows(all_rows, MIN_DWELLINGS, MAX_DWELLINGS)
    if matched:
        out_file = f"planning_leads_{date.today().isoformat()}.csv"
        write_csv(matched, out_file, OUTPUT_COLUMNS)
        print_summary(matched, MIN_DWELLINGS, MAX_DWELLINGS, DAYS_BACK)
    else:
        print("\n[!] No matches found. Try increasing DAYS_BACK at the top of the script.")
