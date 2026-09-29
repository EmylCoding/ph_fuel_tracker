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
    
    Handles formats like:
        Avg. Diesel price is ₱95.95/L and unleaded is ₱89.55/L
        Avg. Diesel 95.95 PHP
        Average Diesel ₱95.95
    """
    pattern = rf"""
        {label}
        .*?
        (?:price\s+is\s+)?
        (?:₱|PHP)?\s*
        (?P<price>\d{{1,3}}(?:,\d{{3}})*\.\d{{1,2}})
        \s*
        (?:PHP|/L)?
    """

    match = re.search(pattern, text, flags=re.IGNORECASE | re.VERBOSE | re.DOTALL)
    if not match:
        return None

    return float(match.group("price").replace(",", ""))


def fetch_gaswatch_prices():
    """
    Fetch the current average Diesel, Unleaded, and Kerosene prices from GasWatch PH.

    Returns:
        tuple[float | None, float | None, float | None]:
        (diesel_price, gasoline_price, kerosene_price)
    """
    try:
        response = requests.get(
            GASWATCH_URL,
            headers=REQUEST_HEADERS,
            timeout=20,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join(soup.stripped_strings)

        diesel = extract_price(text, r"Avg\.?\s*Diesel")
        gasoline = extract_price(text, r"Avg\.?\s*Unleaded")
        kerosene = extract_price(text, r"Avg\.?\s*Kerosene")

        if diesel is None or gasoline is None:
            print("[WARNING] GasWatch prices could not be parsed.")
            print(f"[DEBUG] Diesel found: {diesel}, Gasoline found: {gasoline}")
            return None, None, None

        print(
            f"[GASWATCH] Diesel: ₱{diesel:.2f}, "
            f"Unleaded: ₱{gasoline:.2f}, "
            f"Kerosene: {f'₱{kerosene:.2f}' if kerosene else 'N/A'}"
        )
        return diesel, gasoline, kerosene

    except requests.RequestException as error:
        print(f"[ERROR] GasWatch request failed: {error}")
        return None, None, None
    except Exception as error:
        print(f"[ERROR] GasWatch parsing failed: {error}")
        return None, None, None

def sync_baselines_with_gaswatch(base_data):
    """
    Compare baselines.json with GasWatch PH.

    When GasWatch reports a new official price:
    1. Update the current Diesel, Gasoline, and Kerosene baselines.
    3. Append the new values to the historical arrays.
    4. Keep only the latest eight values.
    5. Save baselines.json.

    This function is safe to run repeatedly. Once the values match,
    it will not append the same week again.
    """
    gaswatch_diesel, gaswatch_gasoline, gaswatch_kerosene = fetch_gaswatch_prices()

    if gaswatch_diesel is None or gaswatch_gasoline is None:
        print("[SYNC] Skipped because GasWatch data is unavailable.")
        return base_data

    current_diesel = float(base_data.get("current_diesel", 0.0))
    current_gasoline = float(
        base_data.get(
            "current_gasoline",
            base_data.get("current_unleaded", 0.0),
        )
    )
    current_kerosene = float(base_data.get("current_kerosene", 131.0))

    diesel_changed = not np.isclose(
        current_diesel,
        gaswatch_diesel,
        atol=0.005,
    )
    gasoline_changed = not np.isclose(
        current_gasoline,
        gaswatch_gasoline,
        atol=0.005,
    )

    if not diesel_changed and not gasoline_changed:
        print("[SYNC] Baselines already match GasWatch PH.")
        return base_data

    print(
        "[SYNC] New GasWatch prices detected:\n"
        f"  Diesel: ₱{current_diesel:.2f} -> ₱{gaswatch_diesel:.2f}\n"
        f"  Gasoline: ₱{current_gasoline:.2f} -> "
        f"₱{gaswatch_gasoline:.2f}"
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
        base_data.get("historical_gasoline", [])
    )
    historical_kerosene = list(
        base_data.get("historical_kerosene", [])
    )

    historical_diesel.append(round(gaswatch_diesel, 2))
    historical_gasoline.append(round(gaswatch_gasoline, 2))
    historical_kerosene.append(final_kerosene)

    base_data["current_diesel"] = round(gaswatch_diesel, 2)
    base_data["current_gasoline"] = round(gaswatch_gasoline, 2)
    base_data["current_kerosene"] = final_kerosene

    base_data["historical_diesel"] = historical_diesel[-8:]
    base_data["historical_gasoline"] = historical_gasoline[-8:]
    base_data["historical_kerosene"] = historical_kerosene[-8:]

    now_pht = dt.datetime.now(
        dt.timezone(dt.timedelta(hours=8))
    )
    base_data["last_gaswatch_sync"] = now_pht.isoformat()
    base_data["last_anchor"] = now_pht.date().isoformat()

    save_json(BASELINES_FILE, base_data)
    print("[SYNC] baselines.json updated.")

    return base_data


def download_market_data():
    """Download three months of market proxy and exchange-rate data."""
    diesel = yf.Ticker("HO=F").history(period="3mo")["Close"]
    gasoline = yf.Ticker("RB=F").history(period="3mo")["Close"]
    forex = yf.Ticker("PHP=X").history(period="3mo")["Close"]

    frame = pd.concat(
        [
            diesel.rename("d_usd"),
            gasoline.rename("g_usd"),
            forex.rename("forex"),
        ],
        axis=1,
    )

    frame = frame.sort_index().ffill().dropna()

    if frame.empty:
        raise RuntimeError("Yahoo Finance returned no usable data.")

    # Remove timezone information so date comparisons are consistent.
    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_localize(None)

    return frame


def convert_market_units(frame):
    """
    Convert USD/gallon into an estimated PHP/liter value.

    42 gallons per barrel
    158.987 liters per barrel
    12% VAT
    """
    converted = frame.copy()

    converted["d_php_l"] = (
        converted["d_usd"]
        * 42
        * converted["forex"]
        * 1.12
        / 158.987
    )

    converted["g_php_l"] = (
        converted["g_usd"]
        * 42
        * converted["forex"]
        * 1.12
        / 158.987
    )

    return converted


def get_status(delta):
    """Convert a price movement into a display status."""
    if delta <= -0.10:
        return "ROLLBACK"
    if delta >= 0.10:
        return "HIKE"
    return "NO CHANGE"


def calculate_weekly_values(frame):
    """Create weekly market averages and return the prediction windows."""
    weekly = frame.copy()
    iso_calendar = weekly.index.isocalendar()
    weekly["iso_year"] = iso_calendar.year
    weekly["iso_week"] = iso_calendar.week

    weekly = (
        weekly.groupby(["iso_year", "iso_week"])
        .agg(
            d_php_l=("d_php_l", "mean"),
            g_php_l=("g_php_l", "mean"),
            forex=("forex", "mean"),
        )
        .reset_index()
    )

    if len(weekly) < 3:
        raise RuntimeError("Not enough weekly market data for prediction.")

    historical_market = weekly.iloc[-9:-1]
    current_week = weekly.iloc[-1]
    prior_week = weekly.iloc[-2]

    return historical_market, current_week, prior_week


def build_trend(frame, base_data, now_pht):
    """
    Build seven calendar-day trend values.

    Weekends use the latest available market value through forward fill.
    """
    daily = frame[["d_php_l", "g_php_l", "forex"]].copy()
    daily.index = pd.to_datetime(daily.index).normalize()

    # Remove duplicate dates, keeping the last occurrence
    daily = daily[~daily.index.duplicated(keep='last')]

    today = now_pht.date()
    dates = pd.date_range(
        end=pd.Timestamp(today),
        periods=7,
        freq="D",
    )

    daily = daily.reindex(dates).ffill().dropna()

    if daily.empty:
        raise RuntimeError("Could not create a seven-day market trend.")

    tuesday_rows = daily[daily.index.dayofweek == 1]

    if not tuesday_rows.empty:
        anchor = tuesday_rows.iloc[-1]
    else:
        anchor = daily.iloc[0]

    base_diesel = float(base_data["current_diesel"])
    base_gasoline = float(base_data["current_gasoline"])
    base_kerosene = float(base_data["current_kerosene"])

    gasoline_dampener = float(
        base_data.get("gasoline_dampener", 0.85)
    )
    kerosene_factor = float(
        base_data.get("kerosene_factor", 0.92)
    )

    diesel_trend = []
    gasoline_trend = []
    kerosene_trend = []

    for _, row in daily.iterrows():
        diesel_move = row["d_php_l"] - anchor["d_php_l"]
        gasoline_move = row["g_php_l"] - anchor["g_php_l"]

        diesel_trend.append(
            round(base_diesel + diesel_move, 2)
        )
        gasoline_trend.append(
            round(
                base_gasoline
                + gasoline_move * gasoline_dampener,
                2,
            )
        )
        kerosene_trend.append(
            round(
                base_kerosene
                + diesel_move * kerosene_factor,
                2,
            )
        )

    return {
        "dates": [date.strftime("%b %d") for date in daily.index],
        "diesel": diesel_trend,
        "gasoline": gasoline_trend,
        "kerosene": kerosene_trend,
        "forex_rates": [
            round(value, 2)
            for value in daily["forex"].tolist()
        ],
    }


def get_fuel_data():
    """Fetch data, calculate estimates, and write data.json."""
    pht = dt.timezone(dt.timedelta(hours=8))
    now_pht = dt.datetime.now(pht)

    base_data = load_json(BASELINES_FILE)

    if base_data is None:
        raise FileNotFoundError(
            f"Missing required file: {BASELINES_FILE}"
        )

    # GasWatch is the source of truth for the current official baseline.
    # No previous prediction is promoted into the baseline.
    base_data = sync_baselines_with_gaswatch(base_data)

    market = download_market_data()
    market = convert_market_units(market)

    historical_market, current_week, prior_week = (
        calculate_weekly_values(market)
    )

    historical_diesel = np.asarray(
        base_data.get("historical_diesel", []),
        dtype=float,
    )

    if len(historical_market) != len(historical_diesel):
        raise RuntimeError(
            "Historical diesel count does not match market-week count. "
            f"Expected {len(historical_market)}, "
            f"got {len(historical_diesel)}."
        )

    # Historical diesel values are the dependent values in the OLS model.
    # Market diesel values are the independent values.
    slope, intercept = np.polyfit(
        historical_market["d_php_l"].to_numpy(),
        historical_diesel,
        1,
    )

    base_diesel = float(base_data["current_diesel"])
    base_gasoline = float(base_data["current_gasoline"])
    base_kerosene = float(base_data["current_kerosene"])

    gasoline_dampener = float(
        base_data.get("gasoline_dampener", 0.85)
    )
    kerosene_factor = float(
        base_data.get("kerosene_factor", 0.92)
    )

    projected_diesel = (
        current_week["d_php_l"] * slope + intercept
    )
    diesel_delta = round(projected_diesel - base_diesel, 2)

    gasoline_market_delta = (
        current_week["g_php_l"] - prior_week["g_php_l"]
    )
    gasoline_delta = round(
        gasoline_market_delta * gasoline_dampener,
        2,
    )

    kerosene_delta = round(
        diesel_delta * kerosene_factor,
        2,
    )

    trend = build_trend(market, base_data, now_pht)

    payload = {
        "updated_at": now_pht.strftime(
            "%B %d, %Y %I:%M %p PHT"
        ),
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
                "projected_pump_price": round(
                    base_diesel + diesel_delta,
                    2,
                ),
                "status": get_status(diesel_delta),
                "trend": trend["diesel"],
                "dates": trend["dates"],
            },
            "gasoline": {
                "name": "Gasoline",
                "current_pump_price": base_gasoline,
                "est_weekly_impact": gasoline_delta,
                "projected_pump_price": round(
                    base_gasoline + gasoline_delta,
                    2,
                ),
                "status": get_status(gasoline_delta),
                "trend": trend["gasoline"],
                "dates": trend["dates"],
            },
            "kerosene": {
                "name": "Kerosene",
                "current_pump_price": base_kerosene,
                "est_weekly_impact": kerosene_delta,
                "projected_pump_price": round(
                    base_kerosene + kerosene_delta,
                    2,
                ),
                "status": get_status(kerosene_delta),
                "trend": trend["kerosene"],
                "dates": trend["dates"],
            },
        },
    }

    save_json(DATA_FILE, payload)
    print(f"[SUCCESS] Wrote {DATA_FILE}")


if __name__ == "__main__":
    get_fuel_data()
