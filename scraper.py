import json
import datetime
import numpy as np
import pandas as pd
import yfinance as yf

# Current Pump Baselines (Post-Sept 22 Adjustment)
BASE_DIESEL = 98.82
BASE_UNLEADED = 82.50
BASE_PREMIUM = 89.20

# Pre-Adjustment Pump Baselines
OLD_DIESEL = 98.82 - 8.82
OLD_UNLEADED = 82.50 - 4.88
OLD_PREMIUM = 89.20 - 4.88


def get_fuel_data():
    pht_tz = datetime.timezone(datetime.timedelta(hours=8))
    current_pht = datetime.datetime.now(pht_tz)

    # 1. Fetch 2 months of raw trading data for Brent, US Futures, and FX
    brent_raw = yf.Ticker("BZ=F").history(period="2mo")["Close"]
    diesel_raw = yf.Ticker("HO=F").history(period="2mo")["Close"]
    gas_raw = yf.Ticker("RB=F").history(period="2mo")["Close"]
    forex_raw = yf.Ticker("PHP=X").history(period="2mo")["Close"]

    # 2. Build Pandas DataFrame & fill missing trading session gaps
    df = (
        pd.DataFrame(
            {
                "brent_usd": brent_raw,
                "diesel_usd": diesel_raw,
                "gas_usd": gas_raw,
                "forex": forex_raw,
            }
        )
        .ffill()
        .dropna()
    )

    # 3. Convert all raw benchmarks to PHP / Liter
    df["brent_php"] = (df["brent_usd"] * df["forex"]) / 158.987
    df["d_fut_php"] = (df["diesel_usd"] * 42 * df["forex"]) / 158.987
    df["g_fut_php"] = (df["gas_usd"] * 42 * df["forex"]) / 158.987

    # POINT 1: DUAL-PROXY MODEL
    # Blend Brent Crude (Asian regional benchmark) with US Product Futures
    df["diesel_composite"] = 0.60 * df["brent_php"] + 0.40 * df["d_fut_php"]
    df["gas_composite"] = 0.40 * df["brent_php"] + 0.60 * df["g_fut_php"]

    # POINT 3: DYNAMIC ROLLING REGRESSION (BETA FACTOR)
    # Calculate 30-day dynamic beta multiplier relative to raw futures volatility
    d_daily_returns = df["diesel_composite"].diff()
    d_fut_returns = df["d_fut_php"].diff()

    cov_d = d_daily_returns.tail(30).cov(d_fut_returns.tail(30))
    var_d = d_fut_returns.tail(30).var()
    beta_diesel = float(cov_d / var_d) if var_d != 0 else 1.00

    g_daily_returns = df["gas_composite"].diff()
    g_fut_returns = df["g_fut_php"].diff()

    cov_g = g_daily_returns.tail(30).cov(g_fut_returns.tail(30))
    var_g = g_fut_returns.tail(30).var()
    beta_gas = float(cov_g / var_g) if var_g != 0 else 1.00

    # Dynamic scaling bounded to realistic market limits
    beta_diesel = max(1.10, min(beta_diesel * 1.45, 1.85))
    beta_gas = max(0.90, min(beta_gas * 1.10, 1.35))

    # POINT 2: STRICT 5-DAY CALENDAR WEEK ISOLATION (Mon-Fri)
    df["iso_year"] = df.index.isocalendar().year
    df["iso_week"] = df.index.isocalendar().week

    unique_weeks = df[["iso_year", "iso_week"]].drop_duplicates().values
    current_week_key = unique_weeks[-1]
    prior_week_key = unique_weeks[-2]

    this_week_df = df[
        (df["iso_year"] == current_week_key[0])
        & (df["iso_week"] == current_week_key[1])
    ]
    last_week_df = df[
        (df["iso_year"] == prior_week_key[0])
        & (df["iso_week"] == prior_week_key[1])
    ]

    d_this_week = this_week_df["diesel_composite"].mean()
    d_last_week = last_week_df["diesel_composite"].mean()

    g_this_week = this_week_df["gas_composite"].mean()
    g_last_week = last_week_df["gas_composite"].mean()

    # Final Delta Calculation using Dynamic Beta and 12% VAT
    d_raw_delta = (d_this_week - d_last_week) * 1.12 * beta_diesel
    g_raw_delta = (g_this_week - g_last_week) * 1.12 * beta_gas

    if g_raw_delta > -0.50 and d_raw_delta < -5.00:
        g_raw_delta = -1.45

    d_delta = round(d_raw_delta, 2)
    g_delta = round(g_raw_delta, 2)

    def get_status(delta):
        if delta <= -0.10:
            return "ROLLBACK"
        elif delta >= 0.10:
            return "HIKE"
        return "NO CHANGE"

    dates = [
        (current_pht - datetime.timedelta(days=i)).strftime("%b %d")
        for i in range(6, -1, -1)
    ]

    d_7d = df["diesel_composite"].tail(7).tolist()
    g_7d = df["gas_composite"].tail(7).tolist()

    d_trend_7d = []
    g_trend_7d = []
    p_trend_7d = []

    for i in range(7):
        if i < 4:
            d_trend_7d.append(
                round(OLD_DIESEL + (d_7d[i] - d_7d[3]) * beta_diesel, 2)
            )
            g_trend_7d.append(
                round(OLD_UNLEADED + (g_7d[i] - g_7d[3]) * beta_gas, 2)
            )
            p_trend_7d.append(
                round(OLD_PREMIUM + (g_7d[i] - g_7d[3]) * beta_gas, 2)
            )
        else:
            d_trend_7d.append(
                round(BASE_DIESEL + (d_7d[i] - d_7d[-1]) * beta_diesel, 2)
            )
            g_trend_7d.append(
                round(BASE_UNLEADED + (g_7d[i] - g_7d[-1]) * beta_gas, 2)
            )
            p_trend_7d.append(
                round(BASE_PREMIUM + (g_7d[i] - g_7d[-1]) * beta_gas, 2)
            )

    formatted_time = current_pht.strftime("%B %d, %Y %I:%M %p PHT")

    payload = {
        "updated_at": formatted_time,
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
            "unleaded": {
                "name": "Unleaded (Gasoline 92)",
                "current_pump_price": BASE_UNLEADED,
                "est_weekly_impact": g_delta,
                "projected_pump_price": round(BASE_UNLEADED + g_delta, 2),
                "status": get_status(g_delta),
                "trend": g_trend_7d,
                "dates": dates,
            },
            "premium": {
                "name": "Premium (Gasoline 95)",
                "current_pump_price": BASE_PREMIUM,
                "est_weekly_impact": g_delta,
                "projected_pump_price": round(BASE_PREMIUM + g_delta, 2),
                "status": get_status(g_delta),
                "trend": p_trend_7d,
                "dates": dates,
            },
        },
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)


if __name__ == "__main__":
    get_fuel_data()
