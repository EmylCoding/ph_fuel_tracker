import json
import datetime
import yfinance as yf

# Station Pump Baseline as of Tuesday, Sept 22, 2026
BASE_DIESEL = 98.82
BASE_UNLEADED = 82.50
BASE_PREMIUM = 89.20

def get_fuel_data():
    # US Futures proxies (HO=F for Gasoil/Diesel, RB=F for RBOB Gas, PHP=X for USD/PHP)
    diesel_ticker = yf.Ticker("HO=F")
    gas_ticker = yf.Ticker("RB=F")
    forex_ticker = yf.Ticker("PHP=X")

    # Fetch 17 days to ensure 10 trading days for week-over-week 5-day MOPS averages
    # and 7 trading days for the trend display chart
    d_hist = diesel_ticker.history(period="17d")['Close'].tolist()
    g_hist = gas_ticker.history(period="17d")['Close'].tolist()
    f_hist = forex_ticker.history(period="17d")['Close'].tolist()

    current_usd = f_hist[-1]

    # Unit Conversion: USD/gal -> USD/bbl (*42) -> PHP/Liter (/158.987 * Forex)
    d_php_liter = [(val * 42 * current_usd) / 158.987 for val in d_hist]
    g_php_liter = [(val * 42 * current_usd) / 158.987 for val in g_hist]

    # Compute 5-Day MOPS Trading Averages (Current Trading Week vs Prior Trading Week)
    d_this_week_avg = sum(d_php_liter[-5:]) / 5
    d_last_week_avg = sum(d_php_liter[-10:-5]) / 5

    g_this_week_avg = sum(g_php_liter[-5:]) / 5
    g_last_week_avg = sum(g_php_liter[-10:-5]) / 5

    # Net movement including 12% VAT and MOPS Asian Cargo spread factors
    # Accounts for the drop following crude route stabilization
    raw_d_delta = (d_this_week_avg - d_last_week_avg) * 1.12 * 2.30
    raw_g_delta = (g_this_week_avg - g_last_week_avg) * 1.12 * 1.20

    d_delta = round(raw_d_delta, 2)
    g_delta = round(raw_g_delta, 2)

    def get_status(delta):
        if delta <= -0.10:
            return "ROLLBACK"
        elif delta >= 0.10:
            return "HIKE"
        return "NO CHANGE"

    # Generate 7-day date labels for the frontend graph
    dates = [(datetime.datetime.now() - datetime.timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]

    # Compute 7-day trend arrays normalized to current station pump prices
    d_trend_7d = [round(BASE_DIESEL + (p - d_php_liter[-1]), 2) for p in d_php_liter[-7:]]
    g_trend_7d = [round(BASE_UNLEADED + (p - g_php_liter[-1]), 2) for p in g_php_liter[-7:]]
    p_trend_7d = [round(BASE_PREMIUM + (p - g_php_liter[-1]), 2) for p in g_php_liter[-7:]]

    payload = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M PHT"),
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
