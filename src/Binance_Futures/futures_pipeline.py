import pandas as pd
import yfinance as yf
import requests
import numpy as np
import argparse
from datetime import datetime, timedelta, timezone

# --- ARGUMENTS ---
parser = argparse.ArgumentParser()
parser.add_argument("--asset", type=str, default="BTC", choices=["BTC", "ETH", "SOL"])
args = parser.parse_args()

# --- CONFIG ---
# Binance Futures Symbols are usually Asset + USDT
ASSET_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT"
}
SYMBOL = ASSET_MAP[args.asset]
OUTPUT_FILE = f"futures_data_{args.asset}.csv"

# --- 6-HOUR STRATEGY SETTINGS ---
LOOKAHEAD_HOURS = 6   
TARGET_PCT = 0.015    # 1.5% Move

def fetch_binance_history(symbol, interval="1h", lookback_days=730):
    print(f"📉 Fetching {symbol} data from Binance Futures ({lookback_days} days)...")
    
    # Binance API Limits: 1500 candles per request
    base_url = "https://fapi.binance.com/fapi/v1/klines"
    
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = int((datetime.now(timezone.utc) - timedelta(days=lookback_days)).timestamp() * 1000)
    
    all_data = []
    
    current_start = start_time
    
    while True:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": 1500,
            "startTime": current_start,
            "endTime": end_time
        }
        
        try:
            resp = requests.get(base_url, params=params)
            data = resp.json()
            
            if not data or isinstance(data, dict) and 'code' in data: 
                break # Error or empty
                
            all_data.extend(data)
            
            # Update start time to the last candle + 1ms
            last_timestamp = data[-1][0]
            current_start = last_timestamp + 1
            
            if len(data) < 1500 or current_start >= end_time:
                break
                
            # Be nice to API
            time.sleep(0.1)
            print(f"   ...Fetched {len(all_data)} candles so far")
            
        except Exception as e:
            print(f"Error fetching Binance: {e}")
            break
            
    # Convert to DataFrame
    # Binance Columns: Open Time, Open, High, Low, Close, Volume, ...
    df = pd.DataFrame(all_data, columns=[
        "timestamp", "Open", "High", "Low", "Close", "Volume", 
        "Close_Time", "Quote_Asset_Volume", "Trades", "Taker_Buy_Base", "Taker_Buy_Quote", "Ignore"
    ])
    
    # Clean types
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df['Close'] = df['Close'].astype(float)
    df['Volume'] = df['Volume'].astype(float)
    
    df.set_index('timestamp', inplace=True)
    return df[['Close', 'Volume']]

def calculate_indicators(df):
    # 1. RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # 2. Trend
    df['sma50'] = df['Close'].rolling(50).mean()
    df['trend_signal'] = (df['Close'] - df['sma50']) / df['sma50']
    
    # 3. Volatility
    df['volatility'] = df['Close'].pct_change().rolling(24).std()
    
    # 4. Momentum
    df['momentum_24h'] = df['Close'].pct_change(24)
    
    return df

def fetch_and_process():
    # 1. Get Binance Data (The Asset)
    crypto_df = fetch_binance_history(SYMBOL)
    
    # 2. Get Yahoo Data (The Macro Context)
    print("📉 Fetching Nasdaq (Macro) data from Yahoo...")
    nasdaq = yf.download("^IXIC", period="730d", interval="1h", progress=False)['Close']
    if nasdaq.index.tz is None: nasdaq.index = nasdaq.index.tz_localize('UTC')
    else: nasdaq.index = nasdaq.index.tz_convert('UTC')
    
    # 3. Merge
    # We join Nasdaq onto Crypto timestamps (Left Join)
    df = crypto_df.join(nasdaq.rename("Nasdaq"), how='left')
    
    # Forward fill Nasdaq (Stocks don't trade weekends, Crypto does)
    df['qqq_mom'] = df['Nasdaq'].pct_change(24).ffill()
    
    # Calculate Tech Indicators on the High Quality Binance Data
    df = calculate_indicators(df)

    # Labeling
    df['future_close'] = df['Close'].shift(-LOOKAHEAD_HOURS)
    df['future_return'] = (df['future_close'] - df['Close']) / df['Close']
    df['target'] = (df['future_return'] > TARGET_PCT).astype(int)
    
    df.dropna(inplace=True)
    
    features = ['rsi', 'trend_signal', 'volatility', 'momentum_24h', 'qqq_mom', 'target']
    final_df = df[features]
    
    print(f"📊 Dataset Created: {len(final_df)} rows")
    print(f"   Win Rate: {(final_df['target'].mean()*100):.2f}%")
    
    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"✅ Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    import time
    fetch_and_process()