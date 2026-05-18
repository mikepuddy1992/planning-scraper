# Planning Scraper — Claude Context

## Project overview

Fetches residential planning applications from the planit.org.uk API, filters for developments of 5–30 dwellings, and writes a dated CSV to `output/`.

## Structure

```
scraper/
  planning_scraper.py   # main script — fetch, filter, write CSV
  enricher.py           # (planned) company/director lookups via Companies House
  config.py             # (planned) shared constants extracted from planning_scraper.py
output/
  planning_leads_YYYY-MM-DD.csv
```

## Running

```bash
python scraper/planning_scraper.py
```

Requires `certifi` on macOS for SSL: `pip install certifi`

## Key constants (scraper/planning_scraper.py)

| Constant | Value | Notes |
|---|---|---|
| `MIN_DWELLINGS` | 5 | Lower bound for dwelling filter |
| `MAX_DWELLINGS` | 30 | Upper bound for dwelling filter |
| `DAYS_BACK` | 4 | API `recent=` param; **hard max is 4** |
| `PAGE_SIZE` | 1000 | `pg_sz` and `max_recs` params |

## API

- Base URL: `https://www.planit.org.uk/api/applics/csv`
- Required params: `compress=on&recent=N&pg_sz=1000&max_recs=1000`
- `recent` is capped at 4 by the API (the code clamps silently)
- Response: UTF-8 CSV with BOM (`utf-8-sig`)

## Dwelling count extraction

1. Checks `other_fields.n_dwellings` field directly
2. Falls back to regex matching on `description` — patterns in `DWELLING_PATTERNS` list, ordered most-specific first, each with the count as group 1

## Filtering logic

- Excludes app types: `trees`, `telecoms`, `advertising`
- Excludes descriptions containing: discharge of condition, approval of details, non-material amendment, prior approval, certificate of lawfulness, tree works, advertisement consent, listed building consent, prior notification
- Keeps only rows where dwelling count is in `[MIN_DWELLINGS, MAX_DWELLINGS]`

## Output CSV columns

`_dwelling_count`, `uid`, `area_name`, `description`, `postcode`, `address`, `url`, `app_size`, `app_type`, `app_state`, `start_date`, `other_fields.n_dwellings`, `other_fields.agent_company`, `other_fields.agent_name`, `other_fields.agent_address`, `other_fields.applicant_name`, `other_fields.case_officer`, `other_fields.decision`

## Planned work

- `scraper/enricher.py` — given agent/applicant names from CSV output, look up company numbers and directors via the Companies House API
- `scraper/config.py` — centralise `MIN_DWELLINGS`, `MAX_DWELLINGS`, `DAYS_BACK`, `PAGE_SIZE`, `OUTPUT_COLUMNS` so `enricher.py` can import them without circular deps
