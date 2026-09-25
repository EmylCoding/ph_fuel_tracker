import json
import datetime
import pandas as pd
import numpy as np
import yfinance as yf

# Load all baseline prices, multipliers, and historical references dynamically
with open("baselines.json", "r") as f:
    base_data = json.load(f)

BASE_DIESEL   = base_data.get("current_diesel", 104.91)
BASE_GASOLINE = base_data.get("current_gasoline", base_data.get("current_unleaded", 92.59))
BASE_KEROSENE = base_data.get("current_kerosene", 89.50)

GASOLINE_DAMPENER = base_data.get("gasoline_dampener", 0.85)
KEROSENE_FACTOR   = base_data.get("kerosene_factor", 0.92)

HISTORICAL_GASOLINE = base_data.get("historical_gasoline", [])
HISTORICAL_DIESEL   = base_data.get("historical_diesel", [])

def get_fuel_data():
    pht_tz = datetime.timezone(datetime.timedelta(hours=8))
    current_pht = datetime.datetime.now(pht_tz)

    # 1. Fetch raw trading data from Yahoo Finance
    d_raw = yf.Ticker("HO=F").history(period="3mo")['Close']
    g_raw = yf.Ticker("RB=F").history(period="3mo")['Close']
    f_raw = yf.Ticker("PHP=X").history(period="3mo")['Close']

    df = pd.DataFrame({'d_usd': d_raw, 'g_usd': g_raw, 'forex': f_raw}).ffill().dropna()

    # 2. Convert USD/gal to PHP/Liter (42 gal/bbl, 158.987 L/bbl, 12% VAT)
    df['d_php_l'] = (df['d_usd'] * 42 * df['forex'] * 1.12) / 158.987
    df['g_php_l'] = (df['g_usd'] * 42 * df['forex'] * 1.12) / 158.987

    # 3. Group by ISO Week to compute weekly averages
    df['iso_year'] = df.index.isocalendar().year
    df['iso_week'] = df.index.isocalendar().week

    weekly_df = df.groupby(['iso_year', 'iso_week']).agg({
        'd_php_l': 'mean',
        'g_php_l': 'mean',
        'forex': 'mean'
    }).reset_index()

    historical_8 = weekly_df.iloc[-9:-1] 
    current_week = weekly_df.iloc[-1]
    prior_week   = weekly_df.iloc[-2]

    # 4. Compute Diesel via OLS Regression against dynamic history
    m_diesel, c_diesel = np.polyfit(historical_8['d_php_l'], HISTORICAL_DIESEL, 1)
    projected_diesel   = (current_week['d_php_l'] * m_diesel) + c_diesel
    d_delta            = round(projected_diesel - BASE_DIESEL, 2)

    # 5. Compute Gasoline via WoW Delta and dynamic dampening factor
    raw_g_wow_delta = current_week['g_php_l'] - prior_week['g_php_l']
    g_delta         = round(raw_g_wow_delta * GASOLINE_DAMPENER, 2)

    # 6. Compute Kerosene via dynamic distillate ratio factor
    k_delta = round(d_delta * KEROSENE_FACTOR, 2)

    def get_status(delta):
        if delta <= -0.10:
            return "ROLLBACK"
        elif delta >= 0.10:
            return "HIKE"
        return "NO CHANGE"

    # 7. Generate Chart Trends dynamically
    d_7d = df['d_php_l'].tail(7).tolist()
    g_7d = df['g_php_l'].tail(7).tolist()
    dates = [(current_pht - datetime.timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]

    d_trend_7d = [round((val * m_diesel) + c_diesel, 2) for val in d_7d]
    
    g_base_ref = df['g_php_l'].iloc[-7]
    g_trend_7d = [round(BASE_GASOLINE + ((val - g_base_ref) * GASOLINE_DAMPENER), 2) for val in g_7d]
    
    k_trend_7d = [round(BASE_KEROSENE + (d - BASE_DIESEL) * KEROSENE_FACTOR, 2) for d in d_trend_7d]

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
            "gasoline": {
                "name": "Gasoline",
                "current_pump_price": BASE_GASOLINE,
                "est_weekly_impact": g_delta,
                "projected_pump_price": round(BASE_GASOLINE + g_delta, 2),
                "status": get_status(g_delta),
                "trend": g_trend_7d,
                "dates": dates
            },
            "kerosene": {
                "name": "Kerosene",
                "current_pump_price": BASE_KEROSENE,
                "est_weekly_impact": k_delta,
                "projected_pump_price": round(BASE_KEROSENE + k_delta, 2),
                "status": get_status(k_delta),
                "trend": k_trend_7d,
                "dates": dates
            }
        }
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    get_fuel_data()
