import json
import yfinance as yf
from datetime import datetime

def fetch_calibrated_ph_fuel_data():
    print("Fetching global market indicators and calculating PH pump prices...")

    # 1. USD to PHP Exchange Rate Trend (7 Days)
    usd_php_ticker = yf.Ticker("PHP=X")
    usd_hist = usd_php_ticker.history(period="10d")
    current_usd = float(usd_hist['Close'].iloc[-1])
    usd_trend = [round(float(p), 2) for p in usd_hist['Close'].iloc[-5:].tolist()]
    forex_dates = [d.strftime("%b %d") for d in usd_hist.index[-5:]]

    # 2. Commodity Proxies
    # Diesel Proxy: Heating Oil Futures ('HO=F')
    # Unleaded (92) Proxy: RBOB Gasoline Futures ('RB=F')
    # Premium (95) Proxy: RBOB Gasoline + ~$3.00/bbl Quality Spread
    diesel_ticker = yf.Ticker("HO=F")
    gas_ticker = yf.Ticker("RB=F")

    diesel_hist = diesel_ticker.history(period="10d")
    gas_hist = gas_ticker.history(period="10d")

    # Convert Gallons to Barrels (1 Barrel = 42 US Gallons)
    diesel_bbl = [float(p) * 42 for p in diesel_hist['Close'].tolist()]
    unleaded_bbl = [float(p) * 42 for p in gas_hist['Close'].tolist()]
    premium_bbl = [b + 3.0 for b in unleaded_bbl]

    # 3. 5-Day Moving Average Delta Calculation (Current Week vs Previous Week)
    def calculate_weekly_delta(bbl_prices):
        this_week_avg = sum(bbl_prices[-5:]) / 5.0
        last_week_avg = sum(bbl_prices[-10:-5]) / 5.0
        change_usd_bbl = this_week_avg - last_week_avg
        
        # Convert USD/bbl to PHP/Liter: (USD Delta / 158.987 L) * USD_PHP * 1.12 VAT Factor
        raw_php_delta = (change_usd_bbl / 158.987) * current_usd
        calibrated_delta = round(raw_php_delta * 1.12, 2)
        return calibrated_delta, this_week_avg

    diesel_delta, diesel_bbl_avg = calculate_weekly_delta(diesel_bbl)
    unleaded_delta, unleaded_bbl_avg = calculate_weekly_delta(unleaded_bbl)
    premium_delta, premium_bbl_avg = calculate_weekly_delta(premium_bbl)

    # 4. Station Baselines (Ground Truth as of Sept 20-22, 2026)
    # Diesel base set to Petron visit (₱90.00 pre-hike -> ₱98.82 post Sept 22 hike)
    BASE_DIESEL = 98.82
    BASE_UNLEADED = 82.50
    BASE_PREMIUM = 89.20

    dates = [d.strftime("%b %d") for d in diesel_hist.index[-5:]]

    # Convert 5-day proxy prices into per-liter PHP trend for charts
    diesel_liter_trend = [round(((b / 158.987) * current_usd) + 22.0, 2) for b in diesel_bbl[-5:]]
    unleaded_liter_trend = [round(((b / 158.987) * current_usd) + 20.0, 2) for b in unleaded_bbl[-5:]]
    premium_liter_trend = [round(((b / 158.987) * current_usd) + 22.5, 2) for b in premium_bbl[-5:]]

    # Output Structured Payload
    data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M PHT"),
        "forex": {
            "usd_php": round(current_usd, 2),
            "trend_dates": forex_dates,
            "rates": usd_trend
        },
        "fuels": {
            "diesel": {
                "name": "Diesel",
                "current_pump_price": BASE_DIESEL,
                "est_weekly_impact": diesel_delta,
                "projected_pump_price": round(BASE_DIESEL + diesel_delta, 2),
                "status": "HIKE" if diesel_delta > 0 else "ROLLBACK",
                "proxy_bbl_usd": round(diesel_bbl_avg, 2),
                "trend": diesel_liter_trend,
                "dates": dates
            },
            "unleaded": {
                "name": "Unleaded (Gasoline 92)",
                "current_pump_price": BASE_UNLEADED,
                "est_weekly_impact": unleaded_delta,
                "projected_pump_price": round(BASE_UNLEADED + unleaded_delta, 2),
                "status": "HIKE" if unleaded_delta > 0 else "ROLLBACK",
                "proxy_bbl_usd": round(unleaded_bbl_avg, 2),
                "trend": unleaded_liter_trend,
                "dates": dates
            },
            "premium": {
                "name": "Premium (Gasoline 95)",
                "current_pump_price": BASE_PREMIUM,
                "est_weekly_impact": premium_delta,
                "projected_pump_price": round(BASE_PREMIUM + premium_delta, 2),
                "status": "HIKE" if premium_delta > 0 else "ROLLBACK",
                "proxy_bbl_usd": round(premium_bbl_avg, 2),
                "trend": premium_liter_trend,
                "dates": dates
            }
        }
    }

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

    print("Successfully updated data.json with calibrated PH prices!")

if __name__ == "__main__":
    fetch_calibrated_ph_fuel_data()
