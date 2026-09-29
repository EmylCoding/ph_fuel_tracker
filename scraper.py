import json
import os
from datetime import datetime
import pandas as pd
import pytz
import yfinance as yf

# ==========================================
# 1. TIMEZONE & PATH CONFIG
# ==========================================
pht = pytz.timezone("Asia/Manila")
current_pht = datetime.now(pht)

BASELINES_FILE = "baselines.json"
DATA_FILE = "data.json"

# ==========================================
# 2. LOAD BASELINES
# ==========================================
default_baselines = {
    "current_diesel": 104.91,
    "current_gasoline": 92.59,
    "current_kerosene": 131.0,
    "historical_diesel": [93.5, 88.0, 91.0, 93.0, 88.0, 93.0, 97.11, 104.91],
    "historical_gasoline": [84.0, 78.5, 80.0, 81.0, 78.5, 82.5, 88.0, 92.59],
    "historical_kerosene": [119.8, 114.0, 117.2, 119.5, 114.33, 119.91, 124.53, 131.0],
    "last_anchor": ""
}

if os.path.exists(BASELINES_FILE):
    try:
        with open(BASELINES_FILE, "r") as f:
            baselines = json.load(f)
    except Exception as e:
        print(f"[WARN] Error reading {BASELINES_FILE}, fallback to defaults: {e}")
        baselines = default_baselines
else:
    baselines = default_baselines

# ==========================================
# 3. FETCH YFINANCE MARKET BENCHMARKS
# ==========================================
tickers = ["BZ=F", "RB=F", "HO=F", "PHP=X"]
print("[INFO] Fetching market benchmark data...")
df_raw = yf.download(tickers=tickers, period="21d", interval="1d", progress=False)

if isinstance(df_raw.columns, pd.MultiIndex):
    df_close = df_raw["Close"].copy()
else:
    df_close = df_raw.copy()

df_close = df_close.ffill().bfill()

forex_series = df_close["PHP=X"] if "PHP=X" in df_close else pd.Series(58.5)
brent_series = df_close["BZ=F"] if "BZ=F" in df_close else pd.Series(75.0)
rbob_series = df_close["RB=F"] if "RB=F" in df_close else pd.Series(2.10)
ho_series = df_close["HO=F"] if "HO=F" in df_close else pd.Series(2.30)

df = pd.DataFrame({
    "forex": forex_series,
    "brent": brent_series,
    "rbob": rbob_series,
    "ho": ho_series
}).ffill().bfill()

# Convert benchmarks to PHP per Liter
df["d_php_l"] = (df["brent"] / 158.987) * df["forex"]
df["g_php_l"] = (df["rbob"] / 3.78541) * df["forex"]
df["k_php_l"] = (df["ho"] / 3.78541) * df["forex"]
df.index = pd.to_datetime(df.index)

# ==========================================
# 4. TUESDAY ANCHOR & BASELINE ROLLOVER
# ==========================================
tuesday_rows = df[df.index.dayofweek == 1]

if not tuesday_rows.empty:
    if current_pht.weekday() == 1 and len(tuesday_rows) > 1:
        anchor_date = tuesday_rows.index[-2]
    else:
        anchor_date = tuesday_rows.index[-1]
else:
    anchor_date = df.index[-7]

anchor_str = anchor_date.strftime("%Y-%m-%d")
last_anchor = baselines.get("last_anchor", "")

d_tuesday_mops = df.loc[anchor_date, "d_php_l"]
g_tuesday_mops = df.loc[anchor_date, "g_php_l"]
k_tuesday_mops = df.loc[anchor_date, "k_php_l"]

# Calculate latest daily movements relative to Tuesday anchor
latest_d_delta = df.iloc[-1]["d_php_l"] - d_tuesday_mops
latest_g_delta = df.iloc[-1]["g_php_l"] - g_tuesday_mops
latest_k_delta = df.iloc[-1]["k_php_l"] - k_tuesday_mops

# Execute Tuesday rollover if anchor changed
if last_anchor != anchor_str:
    print(f"[INFO] New Tuesday Anchor detected: {anchor_str}. Rolling historical arrays...")
    
    # Compute new baseline prices based on accumulated adjustment
    new_diesel = round(baselines["current_diesel"] + latest_d_delta, 2)
    new_gasoline = round(baselines["current_gasoline"] + latest_g_delta, 2)
    new_kerosene = round(baselines["current_kerosene"] + latest_k_delta, 2)

    # Update current baseline values
    baselines["current_diesel"] = new_diesel
    baselines["current_gasoline"] = new_gasoline
    baselines["current_kerosene"] = new_kerosene

    # Append new values & maintain sliding window of max 8 entries
    baselines["historical_diesel"] = (baselines.get("historical_diesel", []) + [new_diesel])[-8:]
    baselines["historical_gasoline"] = (baselines.get("historical_gasoline", []) + [new_gasoline])[-8:]
    baselines["historical_kerosene"] = (baselines.get("historical_kerosene", []) + [new_kerosene])[-8:]

    baselines["last_anchor"] = anchor_str

    # Write updated baselines.json back to disk
    with open(BASELINES_FILE, "w") as f:
        json.dump(baselines, f, indent=4)
    print(f"[SUCCESS] Updated {BASELINES_FILE} with new 8-week history.")

base_diesel = float(baselines["current_diesel"])
base_gas = float(baselines["current_gasoline"])
base_kero = float(baselines["current_kerosene"])

# ==========================================
# 5. GENERATE DAILY TREND ARRAYS
# ==========================================
current_week_df = df[df.index >= anchor_date]

dates_list = []
diesel_trend = []
gasoline_trend = []
kerosene_trend = []

for date, row in current_week_df.iterrows():
    d_mvt = row["d_php_l"] - d_tuesday_mops
    g_mvt = row["g_php_l"] - g_tuesday_mops
    k_mvt = row["k_php_l"] - k_tuesday_mops

    dates_list.append(date.strftime("%b %d"))
    diesel_trend.append(round(base_diesel + d_mvt, 2))
    gasoline_trend.append(round(base_gas + g_mvt, 2))
    kerosene_trend.append(round(base_kero + k_mvt, 2))

def get_status(delta):
    if round(delta, 2) > 0.05:
        return "HIKE"
    elif round(delta, 2) < -0.05:
        return "ROLLBACK"
    return "NO CHANGE"

recent_forex_rates = df["forex"].iloc[-7:].round(2).tolist()
forex_latest = round(float(df["forex"].iloc[-1]), 2)

# ==========================================
# 6. OUTPUT JSON FOR INDEX.HTML
# ==========================================
output_payload = {
    "updated_at": current_pht.strftime("%B %d, %Y %I:%M %p PHT"),
    "fuels": {
        "diesel": {
            "est_weekly_impact": round(latest_d_delta, 2),
            "current_pump_price": round(base_diesel, 2),
            "projected_pump_price": round(base_diesel + latest_d_delta, 2),
            "status": get_status(latest_d_delta),
            "dates": dates_list,
            "trend": diesel_trend
        },
        "gasoline": {
            "est_weekly_impact": round(latest_g_delta, 2),
            "current_pump_price": round(base_gas, 2),
            "projected_pump_price": round(base_gas + latest_g_delta, 2),
            "status": get_status(latest_g_delta),
            "dates": dates_list,
            "trend": gasoline_trend
        },
        "kerosene": {
            "est_weekly_impact": round(latest_k_delta, 2),
            "current_pump_price": round(base_kero, 2),
            "projected_pump_price": round(base_kero + latest_k_delta, 2),
            "status": get_status(latest_k_delta),
            "dates": dates_list,
            "trend": kerosene_trend
        }
    },
    "forex": {
        "current": forex_latest,
        "rates": recent_forex_rates
    }
}

with open(DATA_FILE, "w") as f:
    json.dump(output_payload, f, indent=4)

print(f"[SUCCESS] {DATA_FILE} generated.")
