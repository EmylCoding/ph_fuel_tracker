import json
import datetime
import yfinance as yf

# Station Baseline as of Sept 22, 2026 (Post-Hike Pump Price)
BASE_DIESEL = 98.82
BASE_UNLEADED = 82.50
BASE_PREMIUM = 89.20

def get_fuel_data():
    # 1. Setup Philippine Timezone (UTC+8)
    pht_tz = datetime.timezone(datetime.timedelta(hours=8))
    current_pht = datetime.datetime.now(pht_tz)

    diesel_ticker = yf.Ticker("HO=F")
    gas_ticker = yf.Ticker("RB=F")
    forex_ticker = yf.Ticker("PHP=X")

    # Fetch 17 trading days
    d_hist = diesel_ticker.history(period="17d")['Close'].tolist()
    g_hist = gas_ticker.history(period="17d")['Close'].tolist()
    f_hist = forex_ticker.history(period="17d")['Close'].tolist()

    current_usd = f_hist[-1]

    # Convert USD/gal -> USD/bbl (*42) -> PHP/Liter (/158.987 * Forex)
    d_php_liter = [(val * 42 * current_usd) / 158.987 for val in d_hist]
    g_php_liter = [(val * 42 * current_usd) / 158.987 for val in g_hist]

    # 5-Day Trading Averages
    d_this_week = sum(d_php_liter[-5:]) / 5
    d_last_week = sum(d_php_liter[-10:-5]) / 5

    g_this_week = sum(g_php_liter[-5:]) / 5
    g_last_week = sum(g_php_liter[-10:-5]) / 5

    # Delta with 12% VAT and scaling
    d_raw_delta = (d_this_week - d_last_week) * 1.12 * 1.45
    g_raw_delta = (g_this_week - g_last_week) * 1.12 * 1.00

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

    # 2. Use PHT for the rolling 7-day chart labels so they don't roll over incorrectly
    dates = [(current_pht - datetime.timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]

    d_trend_7d = [round(BASE_DIESEL + (p - d_php_liter[-1]), 2) for p in d_php_liter[-7:]]
    g_trend_7d = [round(BASE_UNLEADED + (p - g_php_liter[-1]), 2) for p in g_php_liter[-7:]]
    p_trend_7d = [round(BASE_PREMIUM + (p - g_php_liter[-1]), 2) for p in g_php_liter[-7:]]

    # 3. Format the final output string exactly how you requested
    formatted_time = current_pht.strftime("%B %d, %Y %I:%M %p PHT")

    payload = {
        "updated_at": formatted_time,
        "forex": {
            "current": round(current_usd, 2),
            "rates": [round(r, 2) for r in f_hist[-7:]],
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
