import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

# Define base paths for configuration and output data files
BASE_DIR = Path(__file__).resolve().parent
BASELINES_FILE = BASE_DIR / "baselines.json"
DATA_FILE = BASE_DIR / "data.json"

GASWATCH_URL = "https://gaswatchph.com/"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def load_json(path, default=None):
    """
    Safely load JSON content from a given file path.
    Returns default value if file does not exist.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, value):
    """
    Save python dict or array into JSON format with indentation.
    """
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2)


def fetch_gaswatch_prices():
    """
    Fetch official average Diesel and Unleaded prices from GasWatch PH.
    Searches for specific sentence patterns containing official average figures.
    """
    try:
        response = requests.get(GASWATCH_URL, headers=REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join(soup.stripped_strings)

        # Primary pattern match: "average diesel price is ₱95.95/L and unleaded is ₱89.55/L"
        avg_pattern = r"average\s+diesel\s+price\s+is\s+(?:₱|PHP)\s*([\d.]+).*?unleaded\s+is\s+(?:₱|PHP)\s*([\d.]+)"
        match = re.search(avg_pattern, text, flags=re.IGNORECASE | re.DOTALL)

        if match:
            diesel = float(match.group(1))
            gasoline = float(match.group(2))
            print(f"[GASWATCH] Found official averages - Diesel: ₱{diesel:.2f}, Unleaded: ₱{gasoline:.2f}")
            return diesel, gasoline, None

        # Fallback regex patterns if combined sentence structure differs
        diesel_match = re.search(
            r"average\s+diesel\s+price\s+is\s+(?:₱|PHP)\s*([\d.]+)",
            text,
            flags=re.IGNORECASE
        )
        gasoline_match = re.search(
            r"(?:average\s+)?unleaded\s+(?:price\s+)?is\s+(?:₱|PHP)\s*([\d.]+)",
            text,
            flags=re.IGNORECASE
        )

        if diesel_match and gasoline_match:
            diesel = float(diesel_match.group(1))
            gasoline = float(gasoline_match.group(1))
            print(f"[GASWATCH] Found individual averages - Diesel: ₱{diesel:.2f}, Unleaded: ₱{gasoline:.2f}")
            return diesel, gasoline, None

        print("[WARNING] Could not parse official GasWatch averages from text.")
        return None, None, None

    except requests.RequestException as error:
        print(f"[ERROR] GasWatch web request failed: {error}")
        return None, None, None
    except Exception as error:
        print(f"[ERROR] GasWatch parsing exception: {error}")
        return None, None, None


def sync_baselines_with_gaswatch(base_data):
    """
    Compare stored baselines against fresh GasWatch values.
    Updates baselines and appends historical data if official averages change.
    """
    gaswatch_diesel, gaswatch_gasoline, gaswatch_kerosene = fetch_gaswatch_prices()

    if gaswatch_diesel is None or gaswatch_gasoline is None:
        print("[SYNC] Skipped because GasWatch data is unavailable.")
        return base_data

    current_diesel = float(base_data.get("current_diesel", 0.0))
    current_gasoline = float(base_data.get("current_gasoline", base_data.get("current_unleaded", 0.0)))
    current_kerosene = float(base_data.get("current_kerosene", 123.0))

    diesel_changed = not np.isclose(current_diesel, gaswatch_diesel, atol=0.005)
    gasoline_changed = not np.isclose(current_gasoline, gaswatch_gasoline, atol=0.005)

    if not diesel_changed and not gasoline_changed:
        print("[SYNC] Baselines are up to date with GasWatch PH.")
        return base_data

    print(
        "[SYNC] New GasWatch pump averages detected:\n"
        f"  Diesel:   ₱{current_diesel:.2f} -> ₱{gaswatch_diesel:.2f}\n"
        f"  Gasoline: ₱{current_gasoline:.2f} -> ₱{gaswatch_gasoline:.2f}"
    )

    diesel_delta = gaswatch_diesel - current_diesel
    kero_factor = float(base_data.get("kerosene_factor", 0.92))

    if gaswatch_kerosene is not None:
        new_kerosene = round(gaswatch_kerosene, 2)
    else:
        new_kerosene = round(current_kerosene + (diesel_delta * kero_factor), 2)

    historical_diesel = list(base_data.get("historical_diesel", []))
    historical_gasoline = list(base_data.get("historical_gasoline", []))
    historical_kerosene = list(base_data.get("historical_kerosene", []))

    historical_diesel.append(round(gaswatch_diesel, 2))
    historical_gasoline.append(round(gaswatch_gasoline, 2))
    historical_kerosene.append(round(new_kerosene, 2))

    base_data["current_diesel"] = round(gaswatch_diesel, 2)
    base_data["current_gasoline"] = round(gaswatch_gasoline, 2)
    base_data["current_kerosene"] = round(new_kerosene, 2)

    # Maintain an 8-entry rolling history for linear regression modeling
    base_data["historical_diesel"] = historical_diesel[-8:]
    base_data["historical_gasoline"] = historical_gasoline[-8:]
    base_data["historical_kerosene"] = historical_kerosene[-8:]

    base_data["last_gaswatch_sync"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
    base_data["last_anchor"] = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()

    save_json(BASELINES_FILE, base_data)
    print("[SUCCESS] baselines.json successfully updated.")
    return base_data


def download_market_data():
    """
    Download Heating Oil (HO=F), RBOB Gasoline (RB=F), and USD/PHP Forex (PHP=X)
    from Yahoo Finance across the last 6 months to ensure ample trading history.
    """
    diesel = yf.Ticker("HO=F").history(period="6mo")["Close"]
    gasoline = yf.Ticker("RB=F").history(period="6mo")["Close"]
    forex = yf.Ticker("PHP=X").history(period="6mo")["Close"]

    frame = pd.concat([
        diesel.rename("d_usd"),
        gasoline.rename("g_usd"),
        forex.rename("forex")
    ], axis=1)

    frame = frame.sort_index().ffill().bfill().dropna()
    if frame.empty:
        raise RuntimeError("Yahoo Finance returned no usable market data.")

    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_localize(None)

    return frame


def convert_market_units(frame):
    """
    Converts Gallon-based USD futures to PHP per Liter:
    Formula: (Price in USD/gal * 42 gal/barrel * USDPHP * 1.12 VAT) / 158.987 L/barrel
    """
    converted = frame.copy()

    converted["d_php_l"] = (
        converted["d_usd"] * 42 * converted["forex"] * 1.12 / 158.987
    )
    converted["g_php_l"] = (
        converted["g_usd"] * 42 * converted["forex"] * 1.12 / 158.987
    )

    return converted


def calculate_rolling_values(frame, history_len=8):
    """
    Replaces incomplete ISO week calendar grouping with a fixed 5-trading-day window.
    This eliminates mid-week distortion when scrapers run mid-week.
    """
    df = frame.sort_index().copy()

    if len(df) < (history_len * 5):
        raise RuntimeError(f"Insufficient market data. Need at least {history_len * 5} trading days.")

    # Resample daily data into weekly averages based on Friday closing windows
    weekly_resampled = df.resample("W-FRI").mean().dropna()

    if len(weekly_resampled) < history_len:
        raise RuntimeError("Not enough resampled weekly data points for regression analysis.")

    # Slice the historical market window corresponding to pump price baselines
    historical_market = weekly_resampled.iloc[-history_len:]

    # Use the last 5 trading days as the current trading week representation
    current_5d = df.iloc[-5:]
    current_week = {
        "d_php_l": float(current_5d["d_php_l"].mean()),
        "g_php_l": float(current_5d["g_php_l"].mean()),
        "forex": float(current_5d["forex"].mean()),
    }

    return historical_market, current_week


def get_status(delta):
    """
    Returns movement status label according to industry adjustment conventions.
    """
    if delta <= -0.10:
        return "ROLLBACK"
    if delta >= 0.10:
        return "HIKE"
    return "NO CHANGE"


def build_trend(frame, base_data, now_pht):
    """
    Constructs a smooth 7-day trend series relative to the latest anchor day.
    """
    daily = frame[["d_php_l", "g_php_l", "forex"]].copy()
    daily.index = pd.to_datetime(daily.index).normalize()
    daily = daily[~daily.index.duplicated(keep="last")]

    end_date = pd.Timestamp(now_pht.date())
    dates = pd.date_range(end=end_date, periods=7, freq="D")

    daily = daily.reindex(dates).ffill().bfill().dropna()
    if daily.empty:
        raise RuntimeError("Could not construct 7-day market trend.")

    tuesday_rows = daily[daily.index.dayofweek == 1]
    anchor = tuesday_rows.iloc[-1] if not tuesday_rows.empty else daily.iloc[0]

    base_diesel = float(base_data["current_diesel"])
    base_gasoline = float(base_data["current_gasoline"])
    base_kerosene = float(base_data["current_kerosene"])

    gasoline_dampener = float(base_data.get("gasoline_dampener", 0.85))
    kerosene_factor = float(base_data.get("kerosene_factor", 0.92))

    diesel_trend = []
    gasoline_trend = []
    kerosene_trend = []

    for _, row in daily.iterrows():
        diesel_move = row["d_php_l"] - anchor["d_php_l"]
        gasoline_move = row["g_php_l"] - anchor["g_php_l"]

        diesel_trend.append(round(base_diesel + diesel_move, 2))
        gasoline_trend.append(round(base_gasoline + (gasoline_move * gasoline_dampener), 2))
        kerosene_trend.append(round(base_kerosene + (diesel_move * kerosene_factor), 2))

    return {
        "dates": [d.strftime("%b %d") for d in daily.index],
        "diesel": diesel_trend,
        "gasoline": gasoline_trend,
        "kerosene": kerosene_trend,
        "forex_rates": [round(float(v), 2) for v in daily["forex"].tolist()],
    }


def get_fuel_data():
    """
    Main entry point to execute scraping, data transformation, model fitting, and payload creation.
    """
    pht_tz = dt.timezone(dt.timedelta(hours=8))
    now_pht = dt.datetime.now(pht_tz)

    base_data = load_json(BASELINES_FILE)
    if base_data is None:
        raise FileNotFoundError(f"Missing required configuration file: {BASELINES_FILE}")

    # Step 1: Sync current pump prices with GasWatch PH
    base_data = sync_baselines_with_gaswatch(base_data)

    # Step 2: Download and transform market data
    market = download_market_data()
    market = convert_market_units(market)

    # Step 3: Compute rolling 5-trading-day window metrics
    historical_market, current_week = calculate_rolling_values(market, history_len=8)

    # Step 4: Extract current pump baselines
    base_diesel = float(base_data["current_diesel"])
    base_gasoline = float(base_data["current_gasoline"])
    base_kerosene = float(base_data["current_kerosene"])

    # Step 5: Perform Polyfit Linear Regression across ALL fuel types
    # Diesel Regression
    hist_diesel = np.asarray(base_data.get("historical_diesel", []), dtype=float)
    if len(hist_diesel) < 2:
        hist_diesel = np.array([base_diesel] * len(historical_market))
    
    d_slope, d_intercept = np.polyfit(
        historical_market["d_php_l"].to_numpy()[-len(hist_diesel):],
        hist_diesel,
        1
    )
    projected_diesel = current_week["d_php_l"] * d_slope + d_intercept
    diesel_delta = round(float(projected_diesel - base_diesel), 2)

    # Gasoline Regression (Replaces raw WoW delta calculation)
    hist_gasoline = np.asarray(base_data.get("historical_gasoline", []), dtype=float)
    if len(hist_gasoline) < 2:
        hist_gasoline = np.array([base_gasoline] * len(historical_market))

    g_slope, g_intercept = np.polyfit(
        historical_market["g_php_l"].to_numpy()[-len(hist_gasoline):],
        hist_gasoline,
        1
    )
    projected_gasoline = current_week["g_php_l"] * g_slope + g_intercept
    gasoline_delta = round(float(projected_gasoline - base_gasoline), 2)

    # Kerosene Projection (Derived via Diesel movement correlation factor)
    kerosene_factor = float(base_data.get("kerosene_factor", 0.92))
    kerosene_delta = round(diesel_delta * kerosene_factor, 2)

    # Step 6: Generate visual trend charts
    trend = build_trend(market, base_data, now_pht)

    # Step 7: Construct output payload
    payload = {
        "updated_at": now_pht.strftime("%B %d, %Y %I:%M %p PHT"),
        "source": "GasWatch PH and Yahoo Finance market proxies",
        "forex": {
            "current": round(float(market["forex"].iloc[-1]), 2),
            "rates": trend["forex_rates"],
            "trend_dates": trend["dates"],
        },
        "fuels": {
            "diesel": {
                "name": "Diesel",
                "current_pump_price": base_diesel,
                "est_weekly_impact": diesel_delta,
                "projected_pump_price": round(base_diesel + diesel_delta, 2),
                "status": get_status(diesel_delta),
                "trend": trend["diesel"],
                "dates": trend["dates"],
            },
            "gasoline": {
                "name": "Gasoline",
                "current_pump_price": base_gasoline,
                "est_weekly_impact": gasoline_delta,
                "projected_pump_price": round(base_gasoline + gasoline_delta, 2),
                "status": get_status(gasoline_delta),
                "trend": trend["gasoline"],
                "dates": trend["dates"],
            },
            "kerosene": {
                "name": "Kerosene",
                "current_pump_price": base_kerosene,
                "est_weekly_impact": kerosene_delta,
                "projected_pump_price": round(base_kerosene + kerosene_delta, 2),
                "status": get_status(kerosene_delta),
                "trend": trend["trend_kerosene"] if "trend_kerosene" in trend else trend["kerosene"],
                "dates": trend["dates"],
            },
        },
    }

    save_json(DATA_FILE, payload)
    print(f"[SUCCESS] Wrote updated fuel predictions to {DATA_FILE}")


if __name__ == "__main__":
    get_fuel_data()
