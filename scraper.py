import json
import os
from datetime import datetime
import numpy as np
import pandas as pd
import pytz
import yfinance as yf

# ==========================================
# 1. TIMEZONE & INITIAL SETUP
# ==========================================
pht = pytz.timezone("Asia/Manila")
current_pht = datetime.now(pht)

BASELINES_FILE = "baselines.json"
DATA_FILE = "data.json"

# ==========================================
# 2. SLIDING WINDOW & BASELINE LOADER
# ==========================================
def update_baseline_array(filepath, new_diesel=None, new_gas=None, new_kero=None, max_weeks=8):
    """
    Shifts the historical array by popping the oldest value (left) 
    and appending the newest price (right) when a new Tuesday price is logged.
    """
    if not os.path.exists(filepath):
        return

    with open(filepath, "r") as f:
        data = json.load(f)

    updates = [
        ("historical_diesel", new_diesel),
        ("historical_gasoline", new_gas),
        ("historical_kerosene", new_kero)
    ]

    modified = False
    for key, new_val in updates:
        if new_val is not None and key in data and isinstance(data[key], list):
            data[key].append(float(new_val))
            # Shift array if it exceeds max_weeks (removes index 0)
            while len(data[key]) > max_weeks:
                data[key].pop(0)
            modified = True

    if modified:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
        print(f"[INFO] Updated {filepath} with new official baseline prices.")

def load_baselines(filepath):
    """
    Reads baselines.json and extracts the latest price (index -1) from each historical array.
    """
    default_data = {
        "historical_diesel": [93.50, 88.00, 91.00, 93.00, 88.00, 93.00, 97.11, 104.91],
        "historical_gasoline": [84.00, 78.50, 80.00, 81.00, 78.50, 82.50, 88.00, 92.59],
        "historical_kerosene": [119.80, 114.00, 117.20, 119.50, 114.33, 119.91, 124.53, 131.00]
    }

    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load {filepath}: {e}")
            data = default_data
    else:
        data = default_data

    def get_last_entry(data_dict, key, fallback):
        arr = data_dict.get(key, [])
        if isinstance(arr, list) and len(arr) > 0:
            return float(arr[-1])
        return float(fallback)

    # Pulls the newest value at the end of the array (e.g., 104.91)
    base_diesel = get_last_entry(data, "historical_diesel", 104.91)
    base_gas = get_last_entry(data, "historical_gasoline", 92.59)
    base_kero = get_last_entry(data, "historical_kerosene", 131.00)

    return data, base_diesel, base_gas, base_kero

# Optional: To manually update/shift baseline when new GasWatch prices come in, call:
# update_baseline_array(BASELINES_FILE, new_diesel=95.95, new_gas=88.50, new_kero=125.00)

baselines_dict, base_diesel, base_gas, base_kero = load_baselines(BASELINES_FILE)
print(f"[INFO] Active Baselines -> Diesel: ₱{base_diesel}, Gas: ₱{base_gas}, Kero: ₱{base_kero}")

# Model calibration multipliers
M_DIESEL = 1.00
M_GAS = 1.00
M_KERO = 1.00

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
}).dropna()

# Convert futures to estimated PHP/Liter
df["d_php_l"] = (df["brent"] / 158.987) * df["forex"]
df["g_php_l"] = (df["rbob"] / 3.78541) * df["forex"] if "rbob" in df else df["d_php_l"] * 0.90
df["k_php_l"] = (df["ho"] / 3.78541) * df["forex"] if "ho" in df else df["d_php_l"] * 1.15

df.index = pd.to_datetime(df.index)

# ==========================================
# 4. DETERMINE TUESDAY ANCHOR
# ==========================================
tuesday_rows = df[df.index.dayofweek == 1]

if not tuesday_rows.empty:
    if current_pht.weekday() == 1 and len(tuesday_rows) > 1:
        anchor_date = tuesday_rows.index[-2]
    else:
        anchor_date = tuesday_rows.index[-1]
else:
    anchor_date = df.index[-7]

d_tuesday_mops = df.loc[anchor_date, "d_php_l"]
g_tuesday_mops = df.loc[anchor_date, "g_php_l"]
k_tuesday_mops = df.loc[anchor_date, "k_php_l"]

print(f"[INFO] Anchor Date: {anchor_date.strftime('%Y-%m-%d')} (Tuesday)")

# ==========================================
# 5. GENERATE STATIC DAILY TREND
# ==========================================
trend_data = []
current_week_df = df[df.index >= anchor_date]

for date, row in current_week_df.iterrows():
    d_mvt = (row["d_php_l"] - d_tuesday_mops) * M_DIESEL
    g_mvt = (row["g_php_l"] - g_tuesday_mops) * M_GAS
    k_mvt = (row["k_php_l"] - k_tuesday_mops) * M_KERO

    daily_diesel_proj = base_diesel + d_mvt
    daily_gas_proj = base_gas + g_mvt
    daily_kero_proj = base_kero + k_mvt

    trend_data.append({
        "date": date.strftime("%Y-%m-%d"),
        "diesel_proj": round(daily_diesel_proj, 2),
        "gas_proj": round(daily_gas_proj, 2),
        "kero_proj": round(daily_kero_proj, 2),
        "diesel_delta": round(d_mvt, 2),
        "gas_delta": round(g_mvt, 2),
        "kero_delta": round(k_mvt, 2)
    })

latest = trend_data[-1]

# Forex statistics over last 7 trading days
recent_forex = df["forex"].iloc[-7:]
forex_latest = float(df["forex"].iloc[-1])
forex_high = float(recent_forex.max())
forex_low = float(recent_forex.min())

# ==========================================
# 6. OUTPUT TO DATA.JSON
# ==========================================
output_payload = {
    "updated_at": current_pht.strftime("%B %d, %Y %I:%M %p PHT"),
    "baselines": {
        "diesel": base_diesel,
        "gasoline": base_gas,
        "kerosene": base_kero
    },
    "projected": {
        "diesel": latest["diesel_proj"],
        "gasoline": latest["gas_proj"],
        "kerosene": latest["kero_proj"]
    },
    "expected_adjustment": {
        "diesel": latest["diesel_delta"],
        "gasoline": latest["gas_delta"],
        "kerosene": latest["kero_delta"]
    },
    "forex": {
        "current": round(forex_latest, 2),
        "high_7d": round(forex_high, 2),
        "low_7d": round(forex_low, 2)
    },
    "anchor_date": anchor_date.strftime("%Y-%m-%d"),
    "trend": trend_data
}

with open(DATA_FILE, "w") as f:
    json.dump(output_payload, f, indent=4)

print(f"[SUCCESS] {DATA_FILE} generated successfully.")
