import datetime
import json
import re
from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
import requests
import yfinance as yf

def fetch_gaswatch_prices():
    """
    Scrapes official weekly average pump prices directly from GasWatch PH.
    This acts as the source of truth for Tuesday price implementations.
    """
    url = "https://gaswatchph.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        text = soup.get_text()

        # Extract numerical averages using regex
        diesel_match = re.search(r"Avg\.\s*Diesel\s*([\d\.]+)\s*PHP", text, re.IGNORECASE)
        gas_match = re.search(r"Avg\.\s*Unleaded\s*([\d\.]+)\s*PHP", text, re.IGNORECASE)

        if diesel_match and gas_match:
            gw_diesel = float(diesel_match.group(1))
            gw_gasoline = float(gas_match.group(1))
            print(f"[GASWATCH] Scraped live averages: Diesel = ₱{gw_diesel}, Gasoline = ₱{gw_gasoline}")
            return gw_diesel, gw_gasoline
        else:
            print("[WARNING] Could not parse GasWatch PH price text patterns.")
            return None, None

    except Exception as e:
        print(f"[ERROR] Failed to fetch GasWatch PH prices: {e}")
        return None, None

def sync_baselines_with_gaswatch(base_data):
    """
    Checks if current baselines differ from GasWatch PH.
    If different, updates the current pump prices and shifts the 8-week historical array.
    This automates the Tuesday rollover process.
    """
    gw_diesel, gw_gasoline = fetch_gaswatch_prices()

    if gw_diesel is None or gw_gasoline is None:
        return base_data

    curr_diesel = base_data.get("current_diesel", 0.0)
    curr_gasoline = base_data.get("current_gasoline", base_data.get("current_unleaded", 0.0))

    # Trigger rollover if GasWatch PH shows new official pump averages
    if curr_diesel != gw_diesel or curr_gasoline != gw_gasoline:
        print(
            f"[SYNC] Baseline mismatch detected! Tuesday Rollover Initiated.\n"
            f"  Old Baseline: Diesel ₱{curr_diesel}, Gasoline ₱{curr_gasoline}\n"
            f"  New Baseline: Diesel ₱{gw_diesel}, Gasoline ₱{gw_gasoline}"
        )

        # Calculate proportionate kerosene adjustment based on diesel movement
        diesel_delta = gw_diesel - curr_diesel
        kero_factor = base_data.get("kerosene_factor", 0.92)
        gw_kerosene = round(base_data.get("current_kerosene", 131.00) + (diesel_delta * kero_factor), 2)

        # 1. Overwrite current baseline pump values
        base_data["current_diesel"] = gw_diesel
        base_data["current_gasoline"] = gw_gasoline
        base_data["current_kerosene"] = gw_kerosene

        # 2. Append new averages to 8-week historical regression arrays
        hist_d = base_data.get("historical_diesel", [])
        hist_g = base_data.get("historical_gasoline", [])
        hist_k = base_data.get("historical_kerosene", [])

        hist_d.append(gw_diesel)
        hist_g.append(gw_gasoline)
        hist_k.append(gw_kerosene)

        # Retain only the last 8 weeks for accurate OLS calculation
        base_data["historical_diesel"] = hist_d[-8:]
        base_data["historical_gasoline"] = hist_g[-8:]
        base_data["historical_kerosene"] = hist_k[-8:]

        base_data["last_gaswatch_sync"] = datetime.datetime.now().isoformat()

        # 3. Save updated state back to baselines.json
        with open("baselines.json", "w") as f:
            json.dump(base_data, f, indent=2)

        print("[SUCCESS] Updated baselines.json with official GasWatch PH averages.")
    else:
        print("[INFO] Baseline prices match GasWatch PH averages. No update needed.")

    return base_data

def get_fuel_data():
    """
    Main execution function:
    Fetches raw market proxies, computes week-on-week deltas, and generates trendlines.
    """
    pht_tz = datetime.timezone(datetime.timedelta(hours=8))
    current_pht = datetime.datetime.now(pht_tz)

    # 1. Load baseline configuration and sync with GasWatch PH
    with open("baselines.json", "r") as f:
        base_data = json.load(f)

    base_data = sync_baselines_with_gaswatch(base_data)

    # Establish baseline anchors for delta calculations
    BASE_DIESEL = base_data["current_diesel"]
    BASE_GASOLINE = base_data["current_gasoline"]
    BASE_KEROSENE = base_data["current_kerosene"]

    GASOLINE_DAMPENER = base_data.get("gasoline_dampener", 0.85)
    KEROSENE_FACTOR = base_data.get("kerosene_factor", 0.92)
    HISTORICAL_DIESEL = base_data.get("historical_diesel", [])

    # 2. Fetch live market proxies via yfinance (3 months to cover 8-week history + buffer)
    d_raw = yf.Ticker("HO=F").history(period="3mo")["Close"]
    g_raw = yf.Ticker("RB=F").history(period="3mo")["Close"]
    f_raw = yf.Ticker("PHP=X").history(period="3mo")["Close"]

    # Forward fill to handle non-trading days/weekends, drop early NaNs
    df = pd.DataFrame({"d_usd": d_raw, "g_usd": g_raw, "forex": f_raw}).ffill().dropna()

    # 3. Convert USD/gal to PHP/Liter (42 gal/bbl, 158.987 L/bbl, 12% VAT)
    df["d_php_l"] = (df["d_usd"] * 42 * df["forex"] * 1.12) / 158.987
    df["g_php_l"] = (df["g_usd"] * 42 * df["forex"] * 1.12) / 158.987

    # Group by ISO week for week-on-week averaging
    df["iso_year"] = df.index.isocalendar().year
    df["iso_week"] = df.index.isocalendar().week

    weekly_df = (
        df.groupby(["iso_year", "iso_week"])
        .agg({"d_php_l": "mean", "g_php_l": "mean", "forex": "mean"})
        .reset_index()
    )

    # Extract historical and current windows
    historical_8 = weekly_df.iloc[-9:-1] # Previous 8 full weeks
    current_week = weekly_df.iloc[-1]    # Ongoing week
    prior_week = weekly_df.iloc[-2]      # Directly preceding week

    # 4. Compute Diesel Impact via Ordinary Least Squares (OLS) Regression
    m_diesel, c_diesel = np.polyfit(historical_8["d_php_l"], HISTORICAL_DIESEL, 1)
    projected_diesel = (current_week["d_php_l"] * m_diesel) + c_diesel
    d_delta = round(projected_diesel - BASE_DIESEL, 2)

    # 5. Compute Gasoline Impact via simple WoW difference + dampener
    raw_g_wow_delta = current_week["g_php_l"] - prior_week["g_php_l"]
    g_delta = round(raw_g_wow_delta * GASOLINE_DAMPENER, 2)

    # 6. Compute Kerosene Impact based on Diesel trajectory
    k_delta = round(d_delta * KEROSENE_FACTOR, 2)

    def get_status(delta):
        if delta <= -0.10:
            return "ROLLBACK"
        elif delta >= 0.10:
            return "HIKE"
        return "NO CHANGE"

    # 7. Generate Chart Trends Anchored to the Most Recent Tuesday
    d_7d = df["d_php_l"].tail(7).tolist()
    g_7d = df["g_php_l"].tail(7).tolist()
    
    # Generate labels for the past 7 days up to today
    dates = [(current_pht - datetime.timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]

    # Locate the MOPS price proxy for the most recent Tuesday (pandas dayofweek == 1)
    tuesday_rows = df[df.index.dayofweek == 1]
    
    if not tuesday_rows.empty:
        d_tuesday_mops = tuesday_rows["d_php_l"].iloc[-1]
        g_tuesday_mops = tuesday_rows["g_php_l"].iloc[-1]
    else:
        # Fallback if a Tuesday isn't found (e.g., extremely limited dataframe)
        d_tuesday_mops = df["d_php_l"].iloc[-7]
        g_tuesday_mops = df["g_php_l"].iloc[-7]

    # Calculate actual trendlines mapping MOPS daily variance back to the official Tuesday pump baseline
    d_trend_7d = [
        round(BASE_DIESEL + ((val - d_tuesday_mops) * m_diesel), 2) 
        for val in d_7d
    ]
    
    g_trend_7d = [
        round(BASE_GASOLINE + ((val - g_tuesday_mops) * GASOLINE_DAMPENER), 2) 
        for val in g_7d
    ]
    
    k_trend_7d = [
        round(BASE_KEROSENE + ((val - d_tuesday_mops) * m_diesel * KEROSENE_FACTOR), 2) 
        for val in d_7d
    ]

    # 8. Construct Final JSON Payload
    payload = {
        "updated_at": current_pht.strftime("%B %d, %Y %I:%M %p PHT"),
        "forex": {
            "current": round(df["forex"].iloc[-1], 2),
            "rates": [round(r, 2) for r in df["forex"].tail(7).tolist()],
            "trend_dates": dates,
        },
        "fuels": {
            "diesel": {
                "name": "Diesel",
                "current_pump_price": BASE_DIESEL,
                "est_weekly_impact": d_delta,
                "projected_pump_price": round(BASE_DIESEL + d_delta, 2),
                "status": get_status(d_delta),
                "trend": d_trend_7d,
                "dates": dates,
            },
            "gasoline": {
                "name": "Gasoline",
                "current_pump_price": BASE_GASOLINE,
                "est_weekly_impact": g_delta,
                "projected_pump_price": round(BASE_GASOLINE + g_delta, 2),
                "status": get_status(g_delta),
                "trend": g_trend_7d,
                "dates": dates,
            },
            "kerosene": {
                "name": "Kerosene",
                "current_pump_price": BASE_KEROSENE,
                "est_weekly_impact": k_delta,
                "projected_pump_price": round(BASE_KEROSENE + k_delta, 2),
                "status": get_status(k_delta),
                "trend": k_trend_7d,
                "dates": dates,
            },
        },
    }

    # 9. Output to data.json for the front-end UI
    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    get_fuel_data()
