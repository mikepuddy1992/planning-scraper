# Planning Application Scraper

Fetches new residential planning applications from the [planit.org.uk](https://www.planit.org.uk) API and filters for developments of **5–30 dwellings**, writing the results to a dated CSV in `output/`.

## Requirements

- Python 3.10+
- `certifi` (macOS only, for SSL): `pip install certifi`

No other dependencies — uses the standard library only.

## Usage

```bash
python scraper/planning_scraper.py
```

Output is written to `output/planning_leads_YYYY-MM-DD.csv`.

## Configuration

Edit the constants at the top of `scraper/planning_scraper.py`:

| Constant | Default | Description |
|---|---|---|
| `MIN_DWELLINGS` | `5` | Minimum dwelling count to include |
| `MAX_DWELLINGS` | `30` | Maximum dwelling count to include |
| `DAYS_BACK` | `4` | How many recent days to fetch (API max: 4) |
| `PAGE_SIZE` | `1000` | Records per API request |

## How it works

1. **Fetch** — calls the planit.org.uk CSV API with `compress=on&recent=N&pg_sz=1000&max_recs=1000`
2. **Filter** — removes non-residential types (telecoms, trees, advertising) and administrative applications (condition discharges, amendments, etc.)
3. **Count dwellings** — reads `other_fields.n_dwellings` if present; otherwise extracts the count from the application description using a ranked set of regex patterns
4. **Range filter** — keeps only applications within the configured dwelling range
5. **Write CSV** — saves matched rows to `output/planning_leads_YYYY-MM-DD.csv`

## Output columns

`_dwelling_count`, `uid`, `area_name`, `description`, `postcode`, `address`, `url`, `app_size`, `app_type`, `app_state`, `start_date`, and agent/applicant fields from `other_fields.*`.

## Project structure

```
scraper/
  planning_scraper.py   # main script
  enricher.py           # (planned) Companies House company lookups
  config.py             # (planned) shared settings
output/
  planning_leads_YYYY-MM-DD.csv
```
