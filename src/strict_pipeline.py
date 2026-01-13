import requests
import pandas as pd
import yfinance as yf
import time
import numpy as np
import os
import argparse
from collections import Counter
from bedrock_parser import MarketParser

# --- ARGUMENT PARSING ---
parser = argparse.ArgumentParser(description="Polymarket Data Pipeline")
parser.add_argument("--asset", type=str, default="BTC", choices=["BTC", "ETH", "SOL"], help="Asset to train on")
args = parser.parse_args()

# --- DYNAMIC CONFIGURATION ---
ASSET_MAP = {
    "BTC": {"ticker": "BTC-USD", "keywords": ["bitcoin", "BTC"], "polymarket_tag": ""},
    "ETH": {"ticker": "ETH-USD", "keywords": ["ethereum", "ETH"], "polymarket_tag": ""},
    "SOL": {"ticker": "SOL-USD", "keywords": ["solana", "SOL"], "polymarket_tag": ""}
}

# Dynamically resolve the polymarket_tag for the asset using the slug API
def get_polymarket_tag_for_asset(asset_name):
    slug = asset_name.lower()
    url = f"https://gamma-api.polymarket.com/tags/slug/{slug}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        result = response.json()
        return str(result.get("id"))
    except Exception as e:
        print(f"❌ Could not get Polymarket tag for {asset_name}: {e}")
        return None


for asset, asset_config in ASSET_MAP.items():
    tag = get_polymarket_tag_for_asset(asset_config["keywords"][0])
    if tag:
        ASSET_MAP[asset]["polymarket_tag"] = tag


CURRENT_ASSET = args.asset
CONFIG = ASSET_MAP[CURRENT_ASSET]
OUTPUT_FILE = f"data_{CURRENT_ASSET}.csv" # e.g. data_BTC.csv, data_ETH.csv
MIN_SAMPLES_NEEDED = 100

print(f"🚀 INITIALIZING PIPELINE FOR: {CURRENT_ASSET}")
print(f"   Ticker: {CONFIG['ticker']}")
print(f"   Output: {OUTPUT_FILE}")


# Override the CONFIG['polymarket_tag'] if an up-to-date value is fetched
resolved_tag = get_polymarket_tag_for_asset(CURRENT_ASSET)
if resolved_tag:
    CONFIG["polymarket_tag"] = resolved_tag
    print(f"   Polymarket tag dynamically set to: {resolved_tag}")
else:
    print(f"   Using default polymarket tag for {CURRENT_ASSET}: {CONFIG['polymarket_tag']}")


# --- HELPER: RSI ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- STEP 1: FETCH DYNAMIC FINANCIAL DATA ---
def fetch_market_data():
    print("📉 Fetching fresh financial history (730 days)...")
    
    # We always fetch BTC and Nasdaq for correlation context
    tickers = [CONFIG['ticker'], "BTC-USD", "^IXIC"]
    tickers = list(set(tickers)) # Remove duplicates (if asset is BTC)
    
    data = yf.download(tickers, period="730d", interval="1h", progress=False)['Close']
    
    if data.index.tz is None:
        data.index = data.index.tz_localize('UTC')
    else:
        data.index = data.index.tz_convert('UTC')

    df = pd.DataFrame(index=data.index)
    
    # 1. Target Asset Features (The one we are predicting)
    target_col = CONFIG['ticker']
    df['Price'] = data[target_col]
    df['Ret'] = df['Price'].pct_change()
    df['Vol_24h'] = df['Ret'].rolling(window=24).std()
    df['RSI'] = calculate_rsi(df['Price'], period=14)
    df['SMA50'] = df['Price'].rolling(window=50).mean()
    df['Trend'] = (df['Price'] - df['SMA50']) / df['SMA50']

    # 2. Market Context (Correlations)
    # Always include BTC Context (unless we are trading BTC, then it's redundant but harmless)
    if "BTC-USD" in data.columns:
        df['BTC_Mom'] = data['BTC-USD'].pct_change(24)
    else:
        df['BTC_Mom'] = 0 # Should not happen unless yahoo fails
        
    df['QQQ_Mom'] = data['^IXIC'].pct_change(24).ffill()

    df.dropna(inplace=True)
    print(f"✅ Financial Data Ready: {len(df)} rows.")
    return df

# --- STEP 2: TIME TRAVEL LOOKUP ---
def get_point_in_time_features(df, timestamp):
    if timestamp.tzinfo is None: timestamp = timestamp.tz_localize('UTC')
    
    if timestamp < df.index[0]: return "TOO_OLD"
    if timestamp > df.index[-1]: return "TOO_NEW"
    
    idx = df.index.get_indexer([timestamp], method='pad')[0]
    if idx == -1: return "NO_MATCH"
    
    row = df.iloc[idx]
    
    return {
        "price": float(row['Price']),
        "vol": float(row['Vol_24h']),
        "rsi": float(row['RSI']),
        "trend": float(row['Trend']),
        "btc_mom": float(row['BTC_Mom']),
        "qqq_mom": float(row['QQQ_Mom'])
    }

def load_existing_data():
    if os.path.exists(OUTPUT_FILE):
        try:
            df = pd.read_csv(OUTPUT_FILE)
            seen = set(df['debug_question'].unique())
            print(f"📂 Loaded existing DB: {len(df)} rows.")
            return df, seen
        except: pass
    print("NEW: Starting fresh database.")
    return pd.DataFrame(), set()

# --- MAIN LOOP ---
def process_markets():
    existing_df, seen_questions = load_existing_data()
    parser = MarketParser()
    market_df = fetch_market_data()
    
    new_dataset = []
    offset = 0
    limit = 50 
    
    consecutive_duplicates = 0
    MAX_DUPLICATES = 60 
    total_rejections = Counter()
    
    # Use the primary keyword for the server-side search
    search_query = CONFIG['keywords'][0] 
    
    print(f"\n🔍 Starting Search (Tag: {CONFIG['polymarket_tag']}, Query: {search_query})...")
    
    while True:
        if len(existing_df) == 0 and len(new_dataset) >= MIN_SAMPLES_NEEDED:
            print("✅ Collected enough initial samples.")
            break
        if consecutive_duplicates >= MAX_DUPLICATES:
            print("✅ Overlap detected. Stopping.")
            break

        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "closed": "true",
            "tag_id": CONFIG['polymarket_tag'],
            "slug_contains": search_query,
            "limit": limit,
            "offset": offset, 
            "order": "startDate",
            "ascending": "false"
        }
        
        try:
            r = requests.get(url, params=params)
            r.raise_for_status()
            batch = r.json()
            if not batch: break
            
            batch_rejections = Counter()
            
            for m in batch:
                q_text = m['question']
                # INSERT_YOUR_CODE
                # --- Ignore questions listed in polymarkets_to_ignore.csv ---
                try:
                    import csv
                    with open("polymarkets_to_ignore.csv", "r", encoding="utf-8") as ignore_file:
                        ignored_questions = set(row[0].strip() for row in csv.reader(ignore_file) if row)
                except Exception:
                    ignored_questions = set()
                if q_text in ignored_questions:
                    batch_rejections['Ignored Question'] += 1
                    continue
                
                # 1. Duplication
                if q_text in seen_questions:
                    consecutive_duplicates += 1
                    batch_rejections['Duplicate'] += 1
                    continue
                
                # 2. Dynamic Keyword Check
                # Must contain at least one of the keywords (e.g. "Ethereum" or "ETH")
                if not any(k.lower() in q_text.lower() for k in CONFIG['keywords']):
                    batch_rejections['Keyword Mismatch'] += 1
                    continue

                consecutive_duplicates = 0 

                # 3. Parse (Parser auto-detects asset type from string)
                parsed = parser.parse_question(q_text)
                if not parsed:
                    batch_rejections['Parse Failed'] += 1
                    continue
                
                # Check if parsed asset matches our argument
                if parsed.get('asset') != CURRENT_ASSET:
                    batch_rejections[f'Wrong Asset ({parsed.get("asset")})'] += 1
                    continue

                # 4. Time Alignment
                try:
                    start_dt = pd.to_datetime(m['startDate'])
                    end_dt = pd.to_datetime(m['endDate'])
                except: 
                    batch_rejections['Bad Date'] += 1
                    continue

                feats = get_point_in_time_features(market_df, start_dt)
                if isinstance(feats, str): 
                    batch_rejections[f"Data Error ({feats})"] += 1
                    continue
                if not feats:
                    batch_rejections['No Price Data'] += 1
                    continue

                # 5. Outcome
                res = str(m.get('resolution_outcome', '')).lower()
                label = 1 if res == 'yes' else (0 if res == 'no' else None)
                if label is None and m.get('winner'):
                    if m['winner'] == "Yes": label = 1
                    elif m['winner'] == "No": label = 0
                if label is None: 
                    batch_rejections['No Resolution'] += 1
                    continue

                # 6. Calc Features
                target = parsed['target_price']
                current = feats['price']
                direction = parsed.get('direction', 1)

                if target == "CURRENT_PRICE": target = current
                if not isinstance(target, (int, float)): 
                    batch_rejections['Invalid Target'] += 1
                    continue

                # Moneyness
                if direction == 1: moneyness = np.log(current / target)
                elif direction == -1: moneyness = np.log(target / current)
                else: moneyness = -abs(np.log(current / target))

                hours = (end_dt - start_dt).total_seconds() / 3600
                days_left = max(0.1, hours / 24.0)

                new_dataset.append({
                    "moneyness": moneyness,
                    "days_left": days_left,
                    "vol": feats['vol'],
                    "rsi": feats['rsi'],
                    "trend": feats['trend'],
                    "btc_mom": feats['btc_mom'],
                    "qqq_mom": feats['qqq_mom'],
                    "outcome": label,
                    "debug_question": q_text
                })
                seen_questions.add(q_text)
                print(f"      ✅ NEW: {q_text[:40]}... [L:{label}]")

            print(f"   Batch {offset}-{offset+limit} | New: {len(new_dataset)} | Skipped: {dict(batch_rejections)}")
            total_rejections.update(batch_rejections)
            offset += limit
            time.sleep(0.5)
            
        except Exception as e:
            print(f"❌ Error: {e}")
            break

    print("\n--- 🛑 SCAN COMPLETE ---")
    for reason, count in total_rejections.most_common():
        print(f"   - {reason}: {count}")

    if new_dataset:
        new_df = pd.DataFrame(new_dataset)
        final_df = pd.concat([existing_df, new_df], ignore_index=True) if not existing_df.empty else new_df
        final_df.drop_duplicates(subset=['debug_question'], inplace=True)
        final_df.to_csv(OUTPUT_FILE, index=False)
        print(f"\n💾 DATABASE UPDATED: {OUTPUT_FILE} ({len(final_df)} rows)")
    else:
        print(f"\n✅ {OUTPUT_FILE} is up to date.")

if __name__ == "__main__":
    process_markets()