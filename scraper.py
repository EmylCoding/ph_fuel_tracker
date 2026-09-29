import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
BASELINES_FILE = BASE_DIR / "baselines.json"
DATA_FILE = BASE_DIR / "data.json"

GASWATCH_URL = "https://gaswatchph.com/"
REQUEST_HEADERS = {
"User-Agent": (
"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
"AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
)
}


def load_json(path, default=None):
"""Load JSON from disk and return a default value if the file is missing."""
try:
with path.open("r", encoding="utf-8") as file:
return json.load(file)
except FileNotFoundError:
return default


def save_json(path, value):
"""Save JSON using a consistent readable format."""
with path.open("w", encoding="utf-8") as file:
json.dump(value, file, indent=2)


def extract_price(text, label):
"""
   Find a price after a GasWatch label.

   Handles formats similar to:
       Avg. Diesel 95.95 PHP
       AVG. DIESEL ₱95.95
       Avg. Unleaded 89.55 PHP / liter
   """
pattern = rf"""
       {label}
       \s*
       (?:₱|PHP)?\s*
       (?P<price>\d{{1,3}}(?:,\d{{3}})*\.\d{{1,2}})
       \s*
       (?:PHP)? 
   """

match = re.search(pattern, text, flags=re.IGNORECASE | re.VERBOSE)
if not match:
return None

return float(match.group("price").replace(",", ""))


def fetch_gaswatch_prices():
"""
    Fetch the current average Diesel and Unleaded prices from GasWatch PH.
    Fetch the current average Diesel, Unleaded, and Kerosene prices from GasWatch PH.

   Returns:
        tuple[float | None, float | None]:
        (diesel_price, gasoline_price)
        tuple[float | None, float | None, float | None]:
        (diesel_price, gasoline_price, kerosene_price)
   """
try:
response = requests.get(
@@ -84,6 +84,7 @@

diesel = extract_price(text, r"Avg\.?\s*Diesel")
gasoline = extract_price(text, r"Avg\.?\s*Unleaded")
        kerosene = extract_price(text, r"Avg\.?\s*Kerosene")

if diesel is None or gasoline is None:
# Useful fallback when the page contains unusual spacing or markup.
@@ -94,41 +95,44 @@
gasoline = gasoline or extract_price(
normalized_text, r"Unleaded"
)
            kerosene = kerosene or extract_price(
                normalized_text, r"Kerosene"
            )

if diesel is None or gasoline is None:
print("[WARNING] GasWatch prices could not be parsed.")
print(f"[DEBUG] GasWatch text sample: {text[:500]}")
            return None, None
            return None, None, None

print(
f"[GASWATCH] Diesel: ₱{diesel:.2f}, "
            f"Unleaded: ₱{gasoline:.2f}"
            f"Unleaded: ₱{gasoline:.2f}, "
            f"Kerosene: {f'₱{kerosene:.2f}' if kerosene else 'N/A'}"
)
        return diesel, gasoline
        return diesel, gasoline, kerosene

except requests.RequestException as error:
print(f"[ERROR] GasWatch request failed: {error}")
        return None, None
        return None, None, None
except Exception as error:
print(f"[ERROR] GasWatch parsing failed: {error}")
        return None, None
        return None, None, None


def sync_baselines_with_gaswatch(base_data):
"""
   Compare baselines.json with GasWatch PH.

   When GasWatch reports a new official price:
    1. Update the current Diesel and Gasoline baselines.
    2. Estimate the new Kerosene baseline from Diesel movement.
    1. Update the current Diesel, Gasoline, and Kerosene baselines.
   3. Append the new values to the historical arrays.
   4. Keep only the latest eight values.
   5. Save baselines.json.

   This function is safe to run repeatedly. Once the values match,
   it will not append the same week again.
   """
    gaswatch_diesel, gaswatch_gasoline = fetch_gaswatch_prices()
    gaswatch_diesel, gaswatch_gasoline, gaswatch_kerosene = fetch_gaswatch_prices()

if gaswatch_diesel is None or gaswatch_gasoline is None:
print("[SYNC] Skipped because GasWatch data is unavailable.")
@@ -165,12 +169,18 @@
f"₱{gaswatch_gasoline:.2f}"
)

    diesel_delta = gaswatch_diesel - current_diesel
    kerosene_factor = float(base_data.get("kerosene_factor", 0.92))
    gaswatch_kerosene = round(
        current_kerosene + diesel_delta * kerosene_factor,
        2,
    )
    # If kerosene is available from GasWatch, use it. Otherwise estimate from diesel.
    if gaswatch_kerosene is not None:
        final_kerosene = round(gaswatch_kerosene, 2)
        print(f"  Kerosene: ₱{current_kerosene:.2f} -> ₱{final_kerosene:.2f} (from GasWatch)")
    else:
        kerosene_factor = float(base_data.get("kerosene_factor", 0.92))
        diesel_delta = gaswatch_diesel - current_diesel
        final_kerosene = round(
            current_kerosene + diesel_delta * kerosene_factor,
            2,
        )
        print(f"  Kerosene: ₱{current_kerosene:.2f} -> ₱{final_kerosene:.2f} (estimated from diesel)")

historical_diesel = list(base_data.get("historical_diesel", []))
historical_gasoline = list(
@@ -182,11 +192,11 @@

historical_diesel.append(round(gaswatch_diesel, 2))
historical_gasoline.append(round(gaswatch_gasoline, 2))
    historical_kerosene.append(gaswatch_kerosene)
    historical_kerosene.append(final_kerosene)

base_data["current_diesel"] = round(gaswatch_diesel, 2)
base_data["current_gasoline"] = round(gaswatch_gasoline, 2)
    base_data["current_kerosene"] = gaswatch_kerosene
    base_data["current_kerosene"] = final_kerosene

base_data["historical_diesel"] = historical_diesel[-8:]
base_data["historical_gasoline"] = historical_gasoline[-8:]
