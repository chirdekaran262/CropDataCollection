# Agmarknet Mandi Price Scraper
## For Maharashtra Agri-tech / ML Price Prediction

---

## Step 1 — Feasibility Verification (Is Scraping Possible?)

**YES — confirmed technically feasible with important nuances:**

| Factor | Finding |
|---|---|
| Direct scraping of agmarknet.gov.in | ✅ Works via GET parameters (NO ViewState needed for results) |
| Official API route | ✅ data.gov.in exposes the SAME dataset via REST API (recommended) |
| Blocking / CAPTCHAs | ⚠️ Possible on agmarknet.gov.in if scraped too aggressively |
| robots.txt | ⚠️ Check before heavy scraping; use polite delays |
| Authentication | ❌ None required for data.gov.in API (just free API key) |

---

## Step 2 — How Agmarknet Works (Technical)

### agmarknet.gov.in (HTML site)

The site is an **ASP.NET Web Forms** application hosted on Microsoft IIS.
Most pages have ViewState (`__VIEWSTATE`, `__EVENTVALIDATION`) — but the
**SearchCmmMkt.aspx results page does NOT require a POST**.

You can directly GET the results page with all parameters in the query string:

```
GET https://agmarknet.gov.in/SearchCmmMkt.aspx
  ?Tx_Commodity=0            ← 0 = all commodities
  &Tx_State=MH               ← state code
  &Tx_District=19            ← district ID (Nanded = 19)
  &Tx_Market=0               ← 0 = all markets
  &DateFrom=01-May-2025
  &DateTo=01-May-2025
  &Fr_Date=01-May-2025
  &To_Date=01-May-2025
  &Tx_Trend=0                ← 0 = prices
  &Tx_CommodityHead=--Select--
  &Tx_StateHead=Maharashtra
  &Tx_DistrictHead=Nanded
  &Tx_MarketHead=--Select--
```

The response is HTML with a table (`class="tableagmark_new"`) containing up to 50 rows.
Pagination is handled by clicking "Next" anchor links.

### data.gov.in (Official API — RECOMMENDED)

The same Agmarknet data is published as an open dataset:
- **Catalog URL:** https://data.gov.in/catalog/current-daily-price-various-commodities-various-markets-mandi
- **API Base:** `https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070`
- **Method:** GET
- **Auth:** `?api-key=YOUR_KEY`
- **Filters:** `filters[State]=Maharashtra`, `filters[Arrival_Date]=01-May-2025`
- **Pagination:** `offset` + `limit` (max 1000 per page)

---

## Step 3 — Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Get free API key at https://data.gov.in/user/register
# Then set it:
export DATA_GOV_API_KEY="your_key_here"
```

---

## Step 4 — Usage

```bash
# Fetch today's prices (uses API first, falls back to scraper)
python agmarknet_scraper.py

# Specific date
python agmarknet_scraper.py --date 01-May-2025

# Date range
python agmarknet_scraper.py --from-date 01-Apr-2025 --to-date 30-Apr-2025

# Force HTML scraper only (no API key needed)
python agmarknet_scraper.py --source scraper

# Custom output path
python agmarknet_scraper.py --output /data/mandi/maharashtra.csv
```

---

## Step 5 — Output CSV Schema

```
date, state, district, market, commodity, min_price, max_price, modal_price
01-May-2025, Maharashtra, Nanded, Nanded, Soybean, 4500, 5200, 4900
01-May-2025, Maharashtra, Pune, Pune, Onion, 800, 1200, 1000
```

---

## Step 6 — Daily Scheduling (Cron)

```bash
# Edit crontab
crontab -e

# Run every day at 8:30 AM IST
30 8 * * * /usr/bin/python3 /opt/agmarknet/agmarknet_scraper.py \
    --output /data/mandi/mandi_prices.csv >> /var/log/agmarknet.log 2>&1
```

Or use **systemd timer** for more robustness:

```ini
# /etc/systemd/system/agmarknet.timer
[Unit]
Description=Daily Agmarknet Price Fetch

[Timer]
OnCalendar=*-*-* 08:30:00 Asia/Kolkata
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Step 7 — Real-World Issues & Mitigations

| Issue | Mitigation in Code |
|---|---|
| HTTP 429 Too Many Requests | Retry with exponential backoff (2s→4s→8s→16s) |
| IP blocking by agmarknet.gov.in | Random delays (1.5–6s), realistic browser headers |
| 0 rows returned (weekend/holiday) | Logged as warning, not error; pipeline continues |
| Pagination (50 rows/page) | Auto-follows "Next" anchor until exhausted |
| Session state / cookies | `requests.Session` persists cookies automatically |
| Data gaps or anomalies | Modal price is most reliable; min/max may have outliers |
| API key quota | data.gov.in free tier is generous; 1 daily run << limit |

---

## Step 8 — ML Integration Plan

### For SELL / HOLD / WAIT prediction:

1. **Feature engineering** from this CSV:
   - 7-day rolling average modal price
   - Price vs last 30-day average (momentum)
   - Seasonal flags (Rabi / Kharif / Zaid)
   - District-to-district price spread (arbitrage signal)

2. **Suggested ML pipeline:**
```
CSV → pandas → feature_eng → sklearn/XGBoost → label (SELL/HOLD/WAIT)
```

3. **Label definition** (rule-based → train on):
   - `SELL`  if modal_price > 30-day avg + 1 std deviation
   - `HOLD`  if within ±1 std deviation
   - `WAIT`  if modal_price < 30-day avg − 1 std deviation

4. **Flask API integration:**
```python
from agmarknet_scraper import DataGovFetcher

@app.route("/prices/today")
def today_prices():
    fetcher = DataGovFetcher()
    rows = fetcher.fetch(datetime.today().strftime("%d-%b-%Y"))
    return jsonify(rows)
```

---

## Alternative Data Sources (if scraping fails)

| Source | URL | Notes |
|---|---|---|
| data.gov.in API | https://data.gov.in/catalog/current-daily-price-various-commodities-various-markets-mandi | **BEST** — official, free, REST |
| Agmarknet CEDA mirror | https://agmarknet.ceda.ashoka.edu.in | Cleaned academic dataset |
| Kaggle datasets | https://www.kaggle.com/datasets/arjunyadav99/indian-agricultural-mandi-prices-20232025 | Historical bulk download |
| eNAM dashboard | https://enam.gov.in/web/dashboard/agmarknet | Electronic National Agriculture Market |
| AIKosh (AI dataset) | https://aikosh.indiaai.gov.in/home/datasets/details/variety_wise_daily_market_prices_of_commodity.html | Govt AI dataset hub |

---

## Important Notes

- **Data freshness:** data.gov.in data is typically updated by late morning daily.
- **Missing dates:** Mandis don't report on Sundays and government holidays.
- **Price unit:** All prices are in ₹ per quintal (100 kg).
- **Legal:** Using data.gov.in API is fully legal under NDSAP (National Data Sharing and Accessibility Policy). agmarknet.gov.in scraping should be done politely (low rate, no disruption).
