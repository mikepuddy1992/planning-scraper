"""
Planning Application Scraper
Targets: planit.org.uk API
Filter:  Residential developments of 1-30 dwellings
"""

import csv
import io
import os
import re
import ssl
import urllib.request
from datetime import date

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
MIN_DWELLINGS = 1
MAX_DWELLINGS = 30
DAYS_BACK     = 1      # API is unreliable above recent=1; hard-capped in fetch()
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
    # "10 no. dwellinghouses" / "7 dwellings" / "dwellinghouse" / "dwellinghouses"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?dwellings?(?:houses?)?\b',
    # "10no. residential units" / "10 residential plots" / "10 residential dwellings"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?residential\s+(?:units?|plots?|homes?|dwellings?)',
    # "10 affordable homes" / "10 new homes" / "10 new build homes" / "10 new-build homes"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:affordable\s+|new[\s-]build\s+|new\s+)+homes?',
    # "10 self-contained flats" / "10 new flats" / "10 apartments" / "10 maisonettes"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?(?:self.contained\s+)?(?:flats?|apartments?|maisonettes?)\b',
    # "5 x 3-bedroom houses" / "10 no. 4-bed dwellinghouses" — no./x required to avoid
    # reading "5 bedroom house" (1 house) as 5 dwellings
    r'\b(\d+)\s*(?:no\.?|x)\s+\d+[\s-]bed(?:room)?\s+(?:new\s+)?(?:detached|semi.detached|terraced|linked|town)?\s*(?:houses?|homes?|bungalows?|dwellings?)\b',
    # "10 detached/semi-detached/terraced/affordable houses"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:new\s+)?(?:detached|semi.detached|terraced|affordable|market|linked|town)\s+(?:houses?|homes?|dwellings?)\b',
    # "X affordable/market/shared ownership/social rented units"
    r'\b(\d+)\s*(?:no\.?|x)?\s*(?:affordable|market|shared[\s-]ownership|social[\s-]rented?|help[\s-]to[\s-]buy|starter)\s+(?:housing\s+)?units?',
    # "conversion to/into/of X flats/apartments/units"
    r'conversion\s+(?:to|into|of)\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:flats?|apartments?|dwellings?|residential\s+units?)',
    # "X-storey building containing X flats" — takes the flats count, not the storey count
    r'containing\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:flats?|apartments?|dwellings?|residential\s+units?)',
    # "land for X dwellings/homes/houses" / "site for X dwellings"
    r'(?:land|site)\s+for\s+(?:the\s+)?(?:erection\s+of\s+)?(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|units?)',
    # "outline permission for X dwellings" / "outline planning for X homes"
    r'outline\s+(?:planning\s+)?(?:permission\s+)?for\s+(?:the\s+)?(?:erection\s+of\s+)?(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|units?)',
    # "for 5-7 dwellings" range — take upper number
    r'for\s+\d+[\-–]\s*(\d+)\s*dwellings?',
    # "erection of N" — housing words only, not dimensions
    r'erection\s+of\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|apartments?|residential)',
    # "construction of N dwellings/homes/flats"
    r'construction\s+of\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|apartments?|residential)',
    # "development of N dwellings/homes"
    r'development\s+of\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?)',
    # "into N dwellings/flats" (conversions not caught above)
    r'into\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|flats?|apartments?|units?)',
    # "provide N dwellings/homes/flats"
    r'provide\s+(\d+)\s*(?:no\.?)?\s*(?:new\s+)?(?:dwellings?|houses?|homes?|flats?|apartments?)',
]

# Keywords that suggest a residential application even when no count can be extracted.
# Used to populate the "possible leads" bucket.
RESIDENTIAL_KEYWORDS = [
    "dwelling", "flat", "apartment", "house", "home", "residential",
    "bungalow", "maisonette", "studio flat", "bedsit", "bed-sit",
    "housing", "habitable", "self-contained", "conversion",
]

# App types that are never new residential developments
EXCLUDED_APP_TYPES = {"trees", "telecoms", "advertising"}

# Description phrases that indicate it's NOT a new development
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
    if row.get("app_type", "").lower() in EXCLUDED_APP_TYPES:
        return False
    desc = row.get("description", "").lower()
    if any(phrase in desc for phrase in EXCLUDED_DESC_PHRASES):
        return False
    return True


def has_residential_keywords(row: dict) -> bool:
    desc = row.get("description", "").lower()
    return any(kw in desc for kw in RESIDENTIAL_KEYWORDS)


# ─────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────
def fetch(days_back: int, pg_sz: int) -> list[dict]:
    # Hard cap at 1 — API is unreliable above recent=1
    days_back = min(days_back, 1)
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
    matched, possible = [], []
    skipped_irrelevant = skipped_no_content = skipped_range = 0

    for row in rows:
        if not is_relevant(row):
            skipped_irrelevant += 1
            continue
        count = extract_dwelling_count(row)
        if count is None:
            if has_residential_keywords(row):
                possible.append(row)
            else:
                skipped_no_content += 1
            continue
        if min_dw <= count <= max_dw:
            row["_dwelling_count"] = count
            matched.append(row)
        else:
            skipped_range += 1

    print(f"[✓] {len(matched)} matched ({min_dw}–{max_dw} dwellings)")
    print(f"    {len(possible)} possible leads (residential keywords, no count extracted)")
    print(f"    {skipped_irrelevant} skipped (irrelevant type/conditions)")
    print(f"    {skipped_no_content} skipped (no residential content)")
    print(f"    {skipped_range} skipped (outside size range)")
    return matched, possible


# ─────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────
def write_csv(rows, filepath, columns):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[✓] Saved → {filepath}")


def print_summary(matched, possible, min_dw, max_dw, days_back):
    print(f"\n{'='*70}")
    print(f"  PLANNING LEADS    — {len(matched)} applications ({min_dw}–{max_dw} dwellings)")
    print(f"  POSSIBLE LEADS    — {len(possible)} applications (no count extracted, review manually)")
    print(f"  Last {days_back} day(s)")
    print(f"{'='*70}")
    for r in matched:
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
    os.makedirs("output", exist_ok=True)
    today = date.today().isoformat()

    all_rows = fetch(DAYS_BACK, PAGE_SIZE)
    matched, possible = filter_rows(all_rows, MIN_DWELLINGS, MAX_DWELLINGS)

    if matched:
        leads_file = f"output/planning_leads_{today}.csv"
        write_csv(matched, leads_file, ["_dwelling_count"] + OUTPUT_COLUMNS)

    if possible:
        possible_file = f"output/planning_possible_{today}.csv"
        write_csv(possible, possible_file, OUTPUT_COLUMNS)

    if not matched and not possible:
        print("\n[!] No matches found.")

    print_summary(matched, possible, MIN_DWELLINGS, MAX_DWELLINGS, DAYS_BACK)
