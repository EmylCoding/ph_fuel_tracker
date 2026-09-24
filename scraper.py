import json
import datetime
import yfinance as yfinance

# Base Station Prices as of Sept 22, 2026 (Post +₱8.82 hike)
BASE_DIESEL = 98.82
BASE_UNLEADED = 82.50
BASE_PREMIUM = 89.20

def get_fuel_data():
    # Fetch Gasoil (Diesel proxy) and RBOB (Gasoline proxy)
    diesel_ticker = yfinance.Ticker("HO=F")   # Heating Oil / Gasoil
    gas_ticker = yfinance.Ticker("RB=F")      # RBOB Gasoline
    forex_ticker = yfinance.Ticker("PHP=X")    # USD/PHP

    d_hist = diesel_ticker.history(period="15d")['Close'].tolist()
    g_hist = gas_ticker.history(period="15d")['Close'].tolist()
    f_hist = forex_ticker.history(period="10d")['Close'].tolist()

    current_usd = f_hist[-1]

    # Convert USD/gal to PHP/Liter
    # 1 gal = 3.78541 L
    d_php_liter = [(val * current_usd) / 3.78541 for val in d_hist]
    g_php_liter = [(val * current_usd) / 3.78541 for val in g_hist]

    # Compute 5-Day MOPS Trading Averages (Current Week vs Prior Week)
    d_this_week = sum(d_php_liter[-5:]) / 5
    d_last_week = sum(d_php_liter[-10:-5]) / 5

    g_this_week = sum(g_php_liter[-5:]) / 5
    g_last_week = sum(g_php_liter[-10:-5]) / 5

    # Net Delta including 12% VAT
    d_delta = (d_this_week - d_last_week) * 1.12
    g_delta = (g_this_week - g_last_week) * 1.12

    def format_status(delta):
        if delta < -0.10:
            return "ROLLBACK"
        elif delta > 0.10:
            return "HIKE"
        return "NO CHANGE"

    dates = [(datetime.datetime.now() - datetime.timedelta(days=i)).strftime("%b %d") for i in range(4, -1, -1)]

    payload = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M PHT"),
        "forex": {
            "current": round(current_usd, 2),
            "rates": [round(r, 2) for r in f_hist[-5:]],
            "trend_dates": dates
        },
        "fuels": {
            "diesel": {
                "name": "Diesel",
                "current_pump_price": BASE_DIESEL,
                "est_weekly_impact": round(d_delta, 2),
                "projected_pump_price": round(BASE_DIESEL + d_delta, 2),
                "status": format_status(d_delta),
                "trend": [round(p, 2) for p in d_php_liter[-5:]],
                "dates": dates
            },
            "unleaded": {
                "name": "Unleaded (Gasoline 92)",
                "current_pump_price": BASE_UNLEADED,
                "est_weekly_impact": round(g_delta, 2),
                "projected_pump_price": round(BASE_UNLEADED + g_delta, 2),
                "status": format_status(g_delta),
                "trend": [round(p, 2) for p in g_php_liter[-5:]],
                "dates": dates
            },
            "premium": {
                "name": "Premium (Gasoline 95)",
                "current_pump_price": BASE_PREMIUM,
                "est_weekly_impact": round(g_delta, 2),
                "projected_pump_price": round(BASE_PREMIUM + g_delta, 2),
                "status": format_status(g_delta),
                "trend": [round(p + 6.70, 2) for p in g_php_liter[-5:]],
                "dates": dates
            }
        }
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2)

if __name__ == "__main__":
    get_fuel_data()
