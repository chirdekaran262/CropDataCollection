import requests
from bs4 import BeautifulSoup
import re
import time
import random   # ? added
import pandas as pd
from datetime import datetime

STATE = "maharashtra"

COMMODITY_MARKETS = {
    "turmeric": [
        "basmat", "bhokar", "sangli", "vai", "washim", "mumbai", "hingoli"
    ],
    "onion": [
        "pune", "nashik", "nagpur", "mumbai"
    ],
    "wheat": [
        "akola", "barshi", "bhandara", "jalgaon", "latur"
    ],
    "soyabean": [
        "nagpur", "amravati", "nanded", "latur"
    ],
    "arhar-turred-gram-whole": [
        "amravati", "baramati", "bhokar", "bhusaval",
        "bhandara", "parbhani", "jalna", "pusad",
        "wardha", "washim", "yeotmal"
    ]
}

BASE_URL = "https://www.commodityonline.com/mandiprices/{}/{}/{}"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# =========================
# PRICE EXTRACTION
# =========================
def extract_prices(text):
    text = text.lower()

    avg = re.search(r"average[^0-9]*(\d{4,6})", text)
    low = re.search(r"lowest[^0-9]*(\d{4,6})", text)
    high = re.search(r"(costliest|highest)[^0-9]*(\d{4,6})", text)

    return (
        int(avg.group(1)) if avg else None,
        int(low.group(1)) if low else None,
        int(high.group(2)) if high else None,
    )

# =========================
# SCRAPER
# =========================
def scrape():
    all_data = []

    for commodity, markets in COMMODITY_MARKETS.items():
        print(f"\n--- Scraping {commodity} ---")

        for market in markets:
            url = BASE_URL.format(commodity, STATE, market)

            try:
                res = requests.get(url, headers=HEADERS)

                if res.status_code != 200:
                    print(f"Failed: {commodity} - {market}")
                    continue

                soup = BeautifulSoup(res.text, "html.parser")
                text = soup.get_text(" ", strip=True)

                avg, low, high = extract_prices(text)

                data = {
                    "date": datetime.today().strftime("%Y-%m-%d"),
                    "commodity": commodity,
                    "state": STATE,
                    "market": market,
                    "avg_price": avg,
                    "min_price": low,
                    "max_price": high,
                }

                print(data)
                all_data.append(data)

                delay = random.uniform(5, 15)
                print(f"Sleeping for {delay:.2f} seconds...")
                time.sleep(delay)

            except Exception as e:
                print(f"Error: {commodity}-{market} ? {e}")

    return all_data

# =========================
# SAVE CSV
# =========================
def save_csv(data):
    df = pd.DataFrame(data)

    filename = f"maharashtra_prices_{datetime.today().strftime('%Y-%m-%d')}.csv"
    df.to_csv(filename, index=False)

    print(f"\nSaved: {filename}")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    data = scrape()
    save_csv(data)