# -*- coding: utf-8 -*-
"""
Agmarknet Mandi Price Scraper v3 - Production Ready
=====================================================
Key changes from v2:
  1. Agmarknet 2.0 launched Nov 2025 - old URL /SearchCmmMkt.aspx is DEAD
     New site is at agmarknet.gov.in/home (React/JS app, not scrapable simply)
  2. data.gov.in API returns 0 for today because mandi data arrives
     by EVENING (~4-6 PM IST) - morning runs will always return 0 for today
  3. Script now fetches YESTERDAY by default (reliable data)
  4. Added date validation and clear diagnostics

Primary  : data.gov.in Open Government Data API (official, free)
Fallback : data.gov.in with alternate date formats
Output   : CSV -> date, state, district, market, commodity,
                  min_price, max_price, modal_price

Usage:
    python agmarknet_scraper.py                    # yesterday (safe default)
    python agmarknet_scraper.py --date 04-May-2026 # specific past date
    python agmarknet_scraper.py --from-date 01-Apr-2026 --to-date 04-May-2026
    python agmarknet_scraper.py --test-api          # verify API key works

Scheduling (Windows Task Scheduler - run daily at 8 PM IST):
    Action: python C:/path/to\agmarknet_scraper.py
    Trigger: Daily at 20:00

Cron (Linux - run daily at 6 PM IST = 12:30 UTC):
    30 12 * * * /usr/bin/python3 /path/to/agmarknet_scraper.py
"""

import os
import csv
import time
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==============================================================================
# CONFIGURATION - EDIT THIS SECTION
# ==============================================================================

# STEP 1: Get your FREE API key at https://data.gov.in/user/register
# STEP 2: Paste it here OR set environment variable DATA_GOV_API_KEY
DATA_GOV_API_KEY = os.environ.get("DATA_GOV_API_KEY", "579b464db66ec23bdd0000012060b111b80b4d186097ab868fe3c664")

# data.gov.in resource ID for AGMARKNET daily mandi prices
# Dataset: https://data.gov.in/catalog/current-daily-price-various-commodities-various-markets-mandi
DATA_GOV_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"

# Target state
STATE_FILTER = "Maharashtra"

# Output directory
OUTPUT_DIR = Path("mandi_data")
OUTPUT_DIR.mkdir(exist_ok=True)

# CSV columns (do not change - matches API field names)
CSV_COLUMNS = [
    "date", "state", "district", "market",
    "commodity", "min_price", "max_price", "modal_price"
]

# ==============================================================================
# LOGGING
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_DIR / "scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("agmarknet")


# ==============================================================================
# HTTP SESSION
# ==============================================================================

def build_session():
    """Requests session with retry + backoff on 429/5xx."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
        "Accept": "application/json",
    })
    return session


SESSION = build_session()


# ==============================================================================
# DATA.GOV.IN API FETCHER
# ==============================================================================

class DataGovFetcher:
    """
    Fetches mandi prices from the official data.gov.in API.

    Endpoint: GET https://api.data.gov.in/resource/{resource_id}
    Auth    : ?api-key=YOUR_KEY
    Docs    : https://data.gov.in/help/api

    Important: data.gov.in stores Arrival_Date in multiple formats.
    We try DD/MM/YYYY, DD-Mon-YYYY, and YYYY-MM-DD automatically.
    """
    BASE_URL = "https://api.data.gov.in/resource"

    # All date formats the API accepts / stores (try all for robustness)
    DATE_FORMATS_TO_TRY = [
        "%d/%m/%Y",   # 04/05/2026  <- most common in this dataset
        "%d-%b-%Y",   # 04-May-2026
        "%Y-%m-%d",   # 2026-05-04
    ]

    def check_api_key(self):
        """Test if API key is valid. Returns True/False."""
        if DATA_GOV_API_KEY == "YOUR_API_KEY_HERE":
            log.error(
                "\n"
                "  ============================================================\n"
                "  ERROR: API key not set!\n"
                "  1. Register FREE at: https://data.gov.in/user/register\n"
                "  2. After login, go to: https://data.gov.in/user/me/api-key\n"
                "  3. Copy your key and paste it into this file:\n"
                "     DATA_GOV_API_KEY = 'paste_your_key_here'\n"
                "  ============================================================\n"
            )
            return False

        log.info("[API] Testing API key...")
        params = {
            "api-key": DATA_GOV_API_KEY,
            "format" : "json",
            "limit"  : 1,
            "offset" : 0,
        }
        try:
            resp = SESSION.get(
                "{}/{}".format(self.BASE_URL, DATA_GOV_RESOURCE_ID),
                params=params,
                timeout=15,
            )
            if resp.status_code == 403:
                log.error("[API] 403 Forbidden - API key is invalid or expired.")
                log.error("[API] Get a new key at: https://data.gov.in/user/me/api-key")
                return False
            if resp.status_code == 200:
                data = resp.json()
                total = data.get("total", 0)
                log.info("[API] API key OK. Dataset has %s total records.", total)
                return True
            log.error("[API] Unexpected status %s: %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            log.error("[API] Connection error: %s", exc)
            return False

    def fetch(self, target_date, state=STATE_FILTER):
        """
        Fetch all mandi prices for a state on a given date.

        Args:
            target_date: datetime object
            state      : state name string

        Returns:
            List of row dicts matching CSV_COLUMNS.
        """
        if DATA_GOV_API_KEY == "YOUR_API_KEY_HERE":
            log.error("[API] No API key. Run with --test-api for setup instructions.")
            return []

        # Try each date format - the API's Arrival_Date field format varies
        for date_fmt in self.DATE_FORMATS_TO_TRY:
            date_str = target_date.strftime(date_fmt)
            log.info("[API] Trying date format: '%s' -> '%s'", date_fmt, date_str)
            rows = self._fetch_with_date_str(date_str, state)
            if rows:
                log.info("[API] Got %d rows with format '%s'", len(rows), date_fmt)
                return rows
            time.sleep(0.5)

        log.warning(
            "[API] 0 rows for %s. Possible reasons:\n"
            "  1. Data not uploaded yet (mandis upload by 4-6 PM IST)\n"
            "  2. Today is a public holiday or Sunday (no trading)\n"
            "  3. Try a recent weekday date like: --date %s",
            target_date.strftime("%d-%b-%Y"),
            (datetime.today() - timedelta(days=3)).strftime("%d-%b-%Y"),
        )
        return []

    def _fetch_with_date_str(self, date_str, state):
        """Paginated fetch for a specific date string."""
        rows   = []
        offset = 0
        limit  = 1000

        while True:
            params = {
                "api-key"               : DATA_GOV_API_KEY,
                "format"                : "json",
                "limit"                 : limit,
                "offset"                : offset,
                "filters[State]"        : state,
                "filters[Arrival_Date]" : date_str,
            }

            try:
                resp = SESSION.get(
                    "{}/{}".format(self.BASE_URL, DATA_GOV_RESOURCE_ID),
                    params=params,
                    timeout=30,
                )
            except requests.RequestException as exc:
                log.error("[API] Request error: %s", exc)
                break

            if resp.status_code == 403:
                log.error("[API] 403 Forbidden - check your API key.")
                break

            if resp.status_code != 200:
                log.error("[API] HTTP %s: %s", resp.status_code, resp.text[:200])
                break

            try:
                data = resp.json()
            except ValueError:
                log.error("[API] Invalid JSON: %s", resp.text[:200])
                break

            records = data.get("records", [])
            total   = int(data.get("total", 0))
            log.info("[API] offset=%d  got=%d  total=%d  date='%s'",
                     offset, len(records), total, date_str)

            if not records:
                break

            for r in records:
                rows.append(self._normalise(r))

            offset += limit
            if offset >= total:
                break

            time.sleep(0.3)

        return rows

    @staticmethod
    def _normalise(r):
        """Map API field names to our CSV schema."""
        return {
            "date"        : r.get("Arrival_Date", ""),
            "state"       : r.get("State",        ""),
            "district"    : r.get("District",     ""),
            "market"      : r.get("Market",       ""),
            "commodity"   : r.get("Commodity",    ""),
            "min_price"   : r.get("Min_Price",    ""),
            "max_price"   : r.get("Max_Price",    ""),
            "modal_price" : r.get("Modal_Price",  ""),
        }


# ==============================================================================
# SMART DATE DISCOVERY
# ==============================================================================

def find_latest_available_date(fetcher, days_back=7):
    """
    Walk backward from yesterday until we find a date with data.
    Useful when you don't know the last trading day.
    """
    log.info("[discovery] Searching for latest date with data (up to %d days back)...", days_back)
    for i in range(1, days_back + 1):
        candidate = datetime.today() - timedelta(days=i)
        # Skip Sundays (mandis mostly closed)
        if candidate.weekday() == 6:
            log.info("[discovery] Skipping Sunday %s", candidate.strftime("%d-%b-%Y"))
            continue
        rows = fetcher.fetch(candidate)
        if rows:
            log.info("[discovery] Found data for %s (%d rows)",
                     candidate.strftime("%d-%b-%Y"), len(rows))
            return candidate, rows
        time.sleep(0.5)

    log.error("[discovery] No data found in last %d days.", days_back)
    return None, []


# ==============================================================================
# CSV OUTPUT
# ==============================================================================

def save_csv(rows, output_path):
    """Append rows to CSV; write header if file is new."""
    if not rows:
        return
    is_new = not output_path.exists()
    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
    log.info("[csv] Saved %d rows -> %s", len(rows), output_path)


# ==============================================================================
# DATE UTILITIES
# ==============================================================================

def parse_date(s):
    """Parse user-supplied date string into datetime."""
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(
        "Unrecognised date: '{}'. Use DD-Mon-YYYY e.g. 04-May-2026".format(s)
    )


def date_range(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fetch Maharashtra mandi prices from data.gov.in / agmarknet"
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date in DD-Mon-YYYY (default: auto-find latest available date)",
    )
    parser.add_argument("--from-date", help="Range start DD-Mon-YYYY")
    parser.add_argument("--to-date",   help="Range end DD-Mon-YYYY")
    parser.add_argument(
        "--test-api",
        action="store_true",
        help="Test if your API key works and exit",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DIR / "mandi_prices.csv"),
        help="Output CSV path (default: mandi_data/mandi_prices.csv)",
    )
    args = parser.parse_args()

    fetcher     = DataGovFetcher()
    output_path = Path(args.output)

    # -- API key test mode --
    if args.test_api:
        ok = fetcher.check_api_key()
        if ok:
            print("\nSUCCESS: Your API key is working.")
            print("Run: python agmarknet_scraper.py")
        else:
            print("\nFAILED: Fix your API key first. See instructions above.")
        return

    # -- Verify API key before running --
    if DATA_GOV_API_KEY == "YOUR_API_KEY_HERE":
        fetcher.check_api_key()
        return

    total = 0

    # -- Date range mode --
    if args.from_date and args.to_date:
        start = parse_date(args.from_date)
        end   = parse_date(args.to_date)
        log.info("Date range: %s -> %s", args.from_date, args.to_date)
        for dt in date_range(start, end):
            if dt.weekday() == 6:
                log.info("Skipping Sunday %s", dt.strftime("%d-%b-%Y"))
                continue
            rows = fetcher.fetch(dt)
            save_csv(rows, output_path)
            total += len(rows)
            time.sleep(1)

    # -- Single date mode --
    elif args.date:
        dt   = parse_date(args.date)
        rows = fetcher.fetch(dt)
        save_csv(rows, output_path)
        total = len(rows)

    # -- Auto mode: find latest date with data --
    else:
        log.info("No date specified - auto-finding latest available date...")
        dt, rows = find_latest_available_date(fetcher)
        if rows:
            save_csv(rows, output_path)
            total = len(rows)

    log.info("Done. Total rows written: %d -> %s", total, output_path)

    if total == 0:
        log.warning(
            "\n"
            "  ============================================================\n"
            "  Got 0 rows. Checklist:\n"
            "  1. Is your API key correct? Run: python agmarknet_scraper.py --test-api\n"
            "  2. Mandi data is uploaded by 4-6 PM IST. Run after 6 PM.\n"
            "  3. Try a known past date: --date 02-May-2026\n"
            "  4. Check data.gov.in directly:\n"
            "     https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
            "?api-key=YOUR_KEY&format=json&filters[State]=Maharashtra&limit=5\n"
            "  ============================================================\n"
        )


if __name__ == "__main__":
    main()