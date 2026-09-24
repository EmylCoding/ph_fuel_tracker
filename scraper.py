import json
import os
import yfinance as yf
from datetime import datetime

def fetch_fuel_data():
    print("Fetching fuel proxies and forex market trends...")
    
    # 1. USD/PHP Exchange Rate
    usd_php_ticker = yf.Ticker("PHP=X")
    usd_hist = usd_php_ticker.history(period="7d")
    current_usd = float(usd_hist['Close'].iloc[-1])
    usd_trend = [round(float(p), 2) for p in usd_hist['Close'].tolist()]
    
    # 2. Proxies for Fuel Types:
    # Diesel: Heating Oil ('HO=F') or Gasoil
    # Unleaded (92): RBOB Gasoline ('RB=F')
    # Premium (95): RBOB Gasoline + ~$2.50/bbl quality spread proxy
    diesel_ticker = yf.Ticker("HO=F")      # Heating Oil / Gasoil Proxy (USD/gal)
    gas_ticker = yf.Ticker("RB=F")         # RBOB Gasoline Proxy (USD/gal)
    
    diesel_hist = diesel_ticker.history(period="7d")
    gas_hist = gas_ticker.history(period="7d")
    
    # Convert gallons to barrels (1 barrel = 42 US gallons)
    diesel_bbl_trend = [float(p) * 42 for p in diesel_hist['Close'].tolist()]
    unleaded_bbl_trend = [float(p) * 42 for p in gas_hist['Close'].tolist()]
    # Premium 95 typically trades at a +$2.50 to $4.00/bbl premium over 92 RON
    premium_bbl_trend = [b + 3.0 for b in unleaded_bbl_trend]

    # Calculate per-liter impact formula: (Daily Change USD / 158.987 liters) * USD_PHP_rate
    def calc_liter_impact(bbl_prices):
        change_usd = bbl_prices[-1] - bbl_prices[-2]
        return round((change_usd / 158.987) * current_usd, 2)

    diesel_impact = calc_liter_impact(diesel_bbl_trend)
    unleaded_impact = calc_liter_impact(unleaded_bbl_trend)
    premium_impact = calc_liter_impact(premium_bbl_trend)

    # Historical PHP/L estimated trend for chart rendering
    dates = [d.strftime("%b %d") for d in diesel_hist.index]

    # Structured Output Payload
    data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S PHT"),
        "forex": {
            "usd_php": round(current_usd, 2),
            "trend_dates": [d.strftime("%b %d") for d in usd_hist.index],
            "rates": usd_trend
        },
        "fuels": {
            "diesel": {
                "name": "Diesel",
                "price_bbl": round(diesel_bbl_trend[-1], 2),
                "est_impact": diesel_impact,
                "status": "HIKE" if diesel_impact > 0 else "ROLLBACK",
                "trend": [round((p / 158.987) * current_usd, 2) for p in diesel_bbl_trend],
                "dates": dates
            },
            "unleaded": {
                "name": "Unleaded (Gasoline 92)",
                "price_bbl": round(unleaded_bbl_trend[-1], 2),
                "est_impact": unleaded_impact,
                "status": "HIKE" if unleaded_impact > 0 else "ROLLBACK",
                "trend": [round((p / 158.987) * current_usd, 2) for p in unleaded_bbl_trend],
                "dates": dates
            },
            "premium": {
                "name": "Premium (Gasoline 95)",
                "price_bbl": round(premium_bbl_trend[-1], 2),
                "est_impact": premium_impact,
                "status": "HIKE" if premium_impact > 0 else "ROLLBACK",
                "trend": [round((p / 158.987) * current_usd, 2) for p in premium_bbl_trend],
                "dates": dates
            }
        }
    }

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

    print("Data successfully generated in data.json!")

if __name__ == "__main__":
    fetch_fuel_data()
