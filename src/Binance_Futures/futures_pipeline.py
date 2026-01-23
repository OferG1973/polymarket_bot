import pandas as pd
import yfinance as yf
import requests
import numpy as np
import argparse
import time
import os
from datetime import datetime, timedelta, timezone

# --- ARGUMENTS ---
parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC", choices=["BTC", "ETH", "SOL"])
args = parser.parse_args()

# --- PATH CONFIGURATION ---
DATA_DIR = os.path.join("src", "Binance_Futures")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- CONFIG ---
ASSET_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT"
}
SYMBOL = ASSET_MAP[args.asset]
OUTPUT_FILE = os.path.join(DATA_DIR, f"futures_data_{args.asset}.csv")

# --- 6-HOUR STRATEGY SETTINGS (5x Leverage) ---
LOOKAHEAD_HOURS = 6   
TARGET_PCT = 0.008    # 0.8% Price Move * 5x = 4.0% Profit

def get_target_pct_and_lookahead_hours():
    return TARGET_PCT, LOOKAHEAD_HOURS

def fetch_binance_history(symbol, interval="1h", lookback_days=730):
    print(f"📉 Fetching {symbol} data from Binance Futures...")
    
    base_url = "https://fapi.binance.com/fapi/v1/klines"
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = int((datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp() * 1000)
    
    all_data = []
    current_start = start_time
    
    while True:
        params = {
            "symbol": symbol, "interval": interval, "limit": 1500,
            "startTime": current_start, "endTime": end_time
        }
        
        try:
            resp = requests.get(base_url, params=params)
            data = resp.json()
            if not data or (isinstance(data, dict) and 'code' in data): break 
            all_data.extend(data)
            last_timestamp = data[-1][0]
            current_start = last_timestamp + 1
            if len(data) < 1500 or current_start >= end_time: break
            time.sleep(0.05)
            if len(all_data) % 5000 == 0: print(f"   ...Fetched {len(all_data)} candles")
        except Exception as e:
            print(f"Error fetching Binance: {e}")
            break
            
    df = pd.DataFrame(all_data, columns=[
        "timestamp", "Open", "High", "Low", "Close", "Volume", 
        "Close_Time", "Quote_Asset_Volume", "Trades", "Taker_Buy_Base", "Taker_Buy_Quote", "Ignore"
    ])
    
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df['Close'] = df['Close'].astype(float)
    df['Volume'] = df['Volume'].astype(float)
    
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='first')]
    return df[['Close', 'Volume']]

def calculate_indicators(df):
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # Trend
    df['sma50'] = df['Close'].rolling(50).mean()
    df['trend_signal'] = (df['Close'] - df['sma50']) / df['sma50']
    
    # Volatility & Momentum
    df['volatility'] = df['Close'].pct_change().rolling(24).std()
    df['momentum_24h'] = df['Close'].pct_change(24)
    
    return df

def fetch_and_process():
    # 1. BINANCE
    crypto_df = fetch_binance_history(SYMBOL)
    print(f"✅ Crypto Data: {len(crypto_df)} rows")

    # 2. MACRO (Nasdaq QQQ)
    print("📉 Fetching Nasdaq (QQQ) data from Yahoo...")
    try:
        nasdaq_raw = yf.download("QQQ", period="730d", interval="1h", progress=False)
        
        if isinstance(nasdaq_raw.columns, pd.MultiIndex):
            nasdaq = nasdaq_raw['Close'].iloc[:, 0]
        else:
            nasdaq = nasdaq_raw['Close']
            
        if nasdaq.index.tz is None: nasdaq.index = nasdaq.index.tz_localize('UTC')
        else: nasdaq.index = nasdaq.index.tz_convert('UTC')
        
        nasdaq.name = "Nasdaq"
        nasdaq = nasdaq.sort_index()
        print(f"✅ Macro Data: {len(nasdaq)} rows")
        
    except Exception as e:
        print(f"⚠️ Yahoo Download Failed: {e}")
        nasdaq = pd.Series(dtype=float)

    # 3. MERGE
    df = pd.merge_asof(
        crypto_df, nasdaq, left_index=True, right_index=True, 
        direction='backward', tolerance=pd.Timedelta(days=5)
    )
    
    df['Nasdaq'] = df['Nasdaq'].ffill()
    
    if df['Nasdaq'].isnull().all():
        print("⚠️ Warning: No Nasdaq data matched. Setting macro momentum to 0.")
        df['qqq_mom'] = 0.0
    else:
        df['qqq_mom'] = df['Nasdaq'].pct_change(24).fillna(0.0)

    # 5. INDICATORS
    df = calculate_indicators(df)

    # 6. LABELS (Multi-Class 0, 1, 2) - 6-hour forward prediction
    # Class 0 (NEUTRAL): Price stays flat (within -TARGET_PCT to +TARGET_PCT)
    # Class 1 (LONG): Price goes UP by more than TARGET_PCT
    # Class 2 (SHORT): Price goes DOWN by more than TARGET_PCT
    df['future_close'] = df['Close'].shift(-LOOKAHEAD_HOURS)
    df['future_return'] = (df['future_close'] - df['Close']) / df['Close']
    
    # Initialize all as NEUTRAL (class 0)
    df['target'] = 0
    # LONG (class 1): Future return > TARGET_PCT (price increases significantly)
    df.loc[df['future_return'] > TARGET_PCT, 'target'] = 1
    # SHORT (class 2): Future return < -TARGET_PCT (price decreases significantly)
    df.loc[df['future_return'] < -TARGET_PCT, 'target'] = 2
    
    df.dropna(subset=['rsi', 'trend_signal', 'volatility', 'target'], inplace=True)
    
    features = ['rsi', 'trend_signal', 'volatility', 'momentum_24h', 'qqq_mom', 'target']
    final_df = df[features]
    
    # Stats
    neut = (final_df['target'] == 0).sum()
    longs = (final_df['target'] == 1).sum()
    shorts = (final_df['target'] == 2).sum()
    
    print(f"📊 Dataset: {len(final_df)} rows")
    print(f"   Neutral (0): {neut}")
    print(f"   Longs   (1): {longs}")
    print(f"   Shorts  (2): {shorts}")
    
    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"✅ Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    fetch_and_process()