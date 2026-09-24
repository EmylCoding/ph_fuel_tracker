import json
import os
import yfinance as yf

def fetch_and_save_data():
    print("Fetching oil proxies and exchange rates...")
    
    # 1. USD to PHP Exchange Rate
    php_ticker = yf.Ticker("PHP=X")
    usd_php = float(php_ticker.history(period="1d")['Close'].iloc[-1])
    
    # 2. Crude Proxy (Brent Crude)
    oil_ticker = yf.Ticker("BZ=F")
    history = oil_ticker.history(period="5d")
    
    current_price = float(history['Close'].iloc[-1])
    prev_price = float(history['Close'].iloc[-2])
    usd_change = current_price - prev_price
    
    # 3. Calculated Pump Impact (PHP per Liter)
    php_change = (usd_change / 158.987) * usd_php

    # 4. Create the JSON output payload
    data = {
        "updated_at": history.index[-1].strftime("%Y-%m-%d %H:%M:%S"),
        "usd_php_rate": round(usd_php, 2),
        "brent_usd": round(current_price, 2),
        "brent_usd_change": round(usd_change, 2),
        "est_php_liter_impact": round(php_change, 2),
        "status": "Increase" if php_change > 0 else "Rollback"
    }

    # Write data to a JSON file in the repository root
    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

    print("Data successfully updated in data.json!")

if __name__ == "__main__":
    fetch_and_save_data()
