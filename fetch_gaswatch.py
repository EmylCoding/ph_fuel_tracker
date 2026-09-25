import json
import re
import requests
import datetime

def sync_baselines():
    pht_tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(pht_tz)
    
    # Fuel price adjustments strictly happen on Tuesdays
    if now.weekday() != 1:
        print("Not Tuesday. Keeping existing baselines.")
        return

    try:
        url = "https://gaswatchph.com/"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        html = response.text
        
        # Extract live averages from GasWatch PH
        diesel_match = re.search(r'Avg\. Diesel ([\d\.]+) PHP', html)
        unleaded_match = re.search(r'Avg\. Unleaded ([\d\.]+) PHP', html)
        
        if diesel_match and unleaded_match:
            new_diesel = float(diesel_match.group(1))
            new_unleaded = float(unleaded_match.group(1))
            
            with open("baselines.json", "r") as f:
                base_data = json.load(f)
                
            # Guardrail: If prices match our JSON, GasWatch hasn't updated its database yet today
            if new_diesel == base_data["current_diesel"]:
                print("GasWatch PH Tuesday prices not live yet. Skipping.")
                return

            # Maintain existing market spread for Premium
            premium_spread = base_data["current_premium"] - base_data["current_unleaded"]
            
            # Rotate current to old
            base_data["old_diesel"] = base_data["current_diesel"]
            base_data["old_unleaded"] = base_data["current_unleaded"]
            base_data["old_premium"] = base_data["current_premium"]
            
            # Inject new live averages
            base_data["current_diesel"] = new_diesel
            base_data["current_unleaded"] = new_unleaded
            base_data["current_premium"] = round(new_unleaded + premium_spread, 2)
            
            with open("baselines.json", "w") as f:
                json.dump(base_data, f, indent=2)
                
            print(f"Synced new baselines: Diesel {new_diesel}, Unleaded {new_unleaded}")
    except Exception as e:
        print(f"Failed to fetch GasWatch PH: {e}")

if __name__ == "__main__":
    sync_baselines()
