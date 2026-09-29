import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime
import pytz

# 1. Setup Timezone and Current Time
pht = pytz.timezone('Asia/Manila')
current_pht = datetime.now(pht)

# 2. Load the Official Baselines
# This should ONLY be updated by your gaswatch sync function, not preemptively overridden.
try:
    with open("baselines.json", "r") as f:
        baselines = json.load(f)
    base_diesel = float(baselines.get("current_diesel", 104.91))
    base_gas = float(baselines.get("current_gas", 95.00))
except FileNotFoundError:
    base_diesel, base_gas = 104.91, 95.00 # Fallbacks

# Your custom multiplier models (adjust these to your actual variables)
m_diesel = 1.0 
m_gas = 1.0

# 3. Fetch Market Data
# Fetching the last 14 days guarantees we capture at least the last two Tuesdays
df = yf.download("BZ=F", period="14d") # Replace BZ=F with your actual MOPS proxies

# (Insert your FX conversion and unit math here to generate d_php_l and g_php_l)
# Example placeholders:
df['d_php_l'] = df['Close'] * 0.8  
df['g_php_l'] = df['Close'] * 0.85 

# 4. Determine the Correct Tuesday Anchor
tuesday_rows = df[df.index.dayofweek == 1]

if not tuesday_rows.empty:
    # If today is Tuesday, anchor to LAST Tuesday's close. Otherwise, use the most recent Tuesday.
    if current_pht.weekday() == 1 and len(tuesday_rows) > 1:
        anchor_date = tuesday_rows.index[-2]
    else:
        anchor_date = tuesday_rows.index[-1]
else:
    # Fallback if no Tuesday is found in the window
    anchor_date = df.index[-7]

d_tuesday_mops = df.loc[anchor_date, "d_php_l"]
g_tuesday_mops = df.loc[anchor_date, "g_php_l"]

# 5. Generate the Static Daily Trendline
trend_data = []

# Filter the dataframe to only include days from the anchor Tuesday up to today
current_week_df = df[df.index >= anchor_date]

for date, row in current_week_df.iterrows():
    # Calculate the cumulative movement for THIS specific day
    d_movement = (row["d_php_l"] - d_tuesday_mops) * m_diesel
    g_movement = (row["g_php_l"] - g_tuesday_mops) * m_gas
    
    # Calculate the projected end-of-day price
    daily_diesel = base_diesel + d_movement
    daily_gas = base_gas + g_movement
    
    # Append to the array. Because historical daily closes don't change, 
    # past days in this array will remain completely static.
    trend_data.append({
        "date": date.strftime("%Y-%m-%d"),
        "diesel_proj": round(daily_diesel, 2),
        "gas_proj": round(daily_gas, 2),
        "d_movement_vs_baseline": round(d_movement, 2)
    })

# 6. Output to data.json for your frontend/graph
output_payload = {
    "baseline_diesel": base_diesel,
    "baseline_gas": base_gas,
    "anchor_date": anchor_date.strftime("%Y-%m-%d"),
    "latest_projected_diesel": trend_data[-1]["diesel_proj"],
    "trend": trend_data
}

with open("data.json", "w") as f:
    json.dump(output_payload, f, indent=4)
    
print(f"Successfully generated trend anchored to {anchor_date.strftime('%Y-%m-%d')}")
