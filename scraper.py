import json
import datetime
import pandas as pd
import yfinance as yf

# Load baselines dynamically from the state file
with open("baselines.json", "r") as f:
    base_data = json.load(f)

BASE_DIESEL = base_data["current_diesel"]
BASE_UNLEADED = base_data["current_unleaded"]
BASE_PREMIUM = base_data["current_premium"]

OLD_DIESEL = base_data["old_diesel"]
OLD_UNLEADED = base_data["old_unleaded"]
OLD_PREMIUM = base_data["old_premium"]

def get_fuel_data():
    pht_tz = datetime.timezone(datetime.timedelta(hours=8))
    current_pht = datetime.datetime.now(pht_tz)

    # 1. Fetch raw trading data from Yahoo Finance
    d_raw = yf.Ticker("HO=F").history(period="1mo")['Close']
    g_raw = yf.Ticker("RB=F").history(period="1mo")['Close']
    f_raw = yf.Ticker("PHP=X").history(period="1mo")['Close']

    df = pd.DataFrame({'d_usd': d_raw, 'g_usd': g_raw, 'forex': f_raw}).ffill().dropna()

    # 2. Convert USD/gal to PHP/Liter
    df['d_php'] = (df['d_usd'] * 42 * df['forex']) / 158.987
    df['g_php'] = (df['g_usd'] * 42 * df['forex']) / 158.987

    # 3. Strict Mon-Fri DOE Calendar Week Isolation
    df['iso_year'] = df.index.isocalendar().year
    df['iso_week'] = df.index.isocalendar().week

    unique_weeks = df[['iso_year', 'iso_week']].drop_duplicates().values
    current_week_key = unique_weeks[-1]
    prior_week_key = unique_weeks[-2]

    this_week_df = df[(df['iso_year'] == current_week_key[0]) & (df['iso_week'] == current_week_key[1])]
    last_week_df = df[(df['iso_year'] == prior_week_key[0]) & (df['iso_week'] == prior_week_key[1])]

    # 4. Compute Averages and Deltas (applying 12% VAT and market scaling)
    d_this_week = this_week_df['d_php'].mean()
    d_last_week = last_week_df['d_php'].mean()
    g_this_week = this_week_df['g_php'].mean()
    g_last_week = last_week_df['g_php'].mean()

    d_raw_delta = (d_this_week - d_last_week) * 1.12 * 1.72
    g_raw_delta = (g_this_week - g_last_week) * 1.12 * 1.00

    # Regional divergence guardrail
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

    # 5. Dynamic Date Awareness for 7-Day Chart
    d_7d = df['d_php'].tail(7).tolist()
    g_7d = df['g_php'].tail(7).tolist()

    dates = []
    d_trend_7d = []
    g_trend_7d = []
    p_trend_7d = []

    # Get the date of the most recent Tuesday
    days_since_tuesday = (current_pht.weekday() - 1) % 7
    most_recent_tuesday = (current_pht - datetime.timedelta(days=days_since_tuesday)).date()

    for i in range(6, -1, -1):
        loop_date = (current_pht - datetime.timedelta(days=i))
        dates.append(loop_date.strftime("%b %d"))
        
        # If loop date is before the most recent Tuesday, anchor to OLD prices
        if loop_date.date() < most_recent_tuesday:
            d_trend_7d.append(round(OLD_DIESEL + (d_7d[6-i] - d_7d[0]), 2))
            g_trend_7d.append(round(OLD_UNLEADED + (g_7d[6-i] - g_7d[0]), 2))
            p_trend_7d.append(round(OLD_PREMIUM + (g_7d[6-i] - g_7d[0]), 2))
        else:
            # If loop date is Tuesday or later, anchor to BASE current prices
            d_trend_7d.append(round(BASE_DIESEL + (d_7d[6-i] - d_7d[-1]), 2))
            g_trend_7d.append(round(BASE_UNLEADED + (g_7d[6-i] - g_7d[-1]), 2))
            p_trend_7d.append(round(BASE_PREMIUM + (g_7d[6-i] - g_7d[-1]), 2))

    formatted_time = current_pht.strftime("%B %d, %Y %I:%M %p PHT")

    payload = {
        "updated_at": formatted_time,
        "forex": {
            "current": round(df['forex'].iloc[-1], 2),
            "rates": [round(r, 2) for r in df['forex'].tail(7).tolist()],
            "trend_dates": dates
        },
        "fuels": {
            "diesel": {
                "name": "Diesel",
                "current_pump_price": BASE_DIESEL,
                "est_weekly_impact": d_delta,
                "projected_pump_price": round(BASE_DIESEL + d_delta, 2),
                "status": get_status(d_delta),
                "trend": d_trend_7d,
                "dates": dates
            },
            "unleaded": {
                "name": "Unleaded (Gasoline 92)",
                "current_pump_price": BASE_UNLEADED,
                "est_weekly_impact": g_delta,
                "projected_pump_price": round(BASE_UNLEADED + g_delta, 2),
                "status": get_status(g_delta),
                "trend": g_trend_7d,
                "dates": dates
            },
            "premium": {
                "name": "Premium (Gasoline 95)",
                "current_pump_price": BASE_PREMIUM,
                "est_weekly_impact": g_delta,
                "projected_pump_price": round(BASE_PREMIUM + g_delta, 2),
                "status": get_status(g_delta),
                "trend": p_trend_7d,
                "dates": dates
            }
        }
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    get_fuel_data()
