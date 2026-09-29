import json
import os
from datetime import datetime
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

# Default baseline fallback values
default_baselines = {
    "last_anchor": "",
    "current_diesel": 58.50,
    "current_gasoline": 62.00,
    "current_kerosene": 70.00
}

# ==========================================
# 2. LOAD & AUTO-UPDATE BASELINES
# ==========================================
if os.path.exists(BASELINES_FILE):
    try:
        with open(BASELINES_FILE, "r") as f:
            baselines_data = json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to read {BASELINES_FILE}, fallback to defaults: {e}")
        baselines_data = default_baselines
else:
    baselines_data = default_baselines

base_diesel = float(baselines_data.get("current_diesel", 58.50))
base_gas = float(baselines_data.get("current_gasoline", 62.00))
base_kero = float(baselines_data.get("current_kerosene", 70.00))

# ==========================================
# 3. FETCH YFINANCE MARKET BENCHMARKS
# ==========================================
tickers = ["BZ=F", "RB=F", "HO=F", "PHP=X"]
print("[INFO] Fetching market data...")
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

# Unit conversions to PHP / Liter
df["d_php_l"] = (df["brent"] / 158.987) * df["forex"]
df["g_php_l"] = (df["rbob"] / 3.78541) * df["forex"]
df["k_php_l"] = (df["ho"] / 3.78541) * df["forex"]
df.index = pd.to_datetime(df.index)

# ==========================================
# 4. DETERMINE TUESDAY ANCHOR & SAVE BASELINE
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

# Check if Tuesday anchor shifted to a new week
last_anchor = baselines_data.get("last_anchor", "")
if last_anchor != anchor_str:
    print(f"[INFO] New weekly anchor detected ({anchor_str}). Updating {BASELINES_FILE}...")
    baselines_data["last_anchor"] = anchor_str
    
    # Save back to disk so baselines.json stays updated
    with open(BASELINES_FILE, "w") as f:
        json.dump(baselines_data, f, indent=4)

d_tuesday_mops = df.loc[anchor_date, "d_php_l"]
g_tuesday_mops = df.loc[anchor_date, "g_php_l"]
k_tuesday_mops = df.loc[anchor_date, "k_php_l"]

# ==========================================
# 5. GENERATE DAILY TREND & DELTAS
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

latest_d_delta = current_week_df.iloc[-1]["d_php_l"] - d_tuesday_mops
latest_g_delta = current_week_df.iloc[-1]["g_php_l"] - g_tuesday_mops
latest_k_delta = current_week_df.iloc[-1]["k_php_l"] - k_tuesday_mops

def get_status(delta):
    if round(delta, 2) > 0.05:
        return "HIKE"
    elif round(delta, 2) < -0.05:
        return "ROLLBACK"
    return "NO CHANGE"

recent_forex_rates = df["forex"].iloc[-7:].round(2).tolist()
forex_latest = round(float(df["forex"].iloc[-1]), 2)

# ==========================================
# 6. EXACT JSON SCHEMA REQUIRED BY INDEX.HTML
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

print(f"[SUCCESS] {DATA_FILE} successfully generated for index.html compatibility.")
